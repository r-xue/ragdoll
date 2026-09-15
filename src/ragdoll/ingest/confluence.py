"""Confluence Server, Data Center, and Cloud ingestion module with incremental change detection."""

from __future__ import annotations

import logging
import re
from typing import Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import dateutil.parser

from llama_index.core import Document
from ragdoll.config import settings
from ragdoll.store.vectordb import get_index, _get_client
from ragdoll.store.safety import GracefulInterrupt

logger = logging.getLogger(__name__)

# Suppress noisy internal urllib3 retry warnings for transient connection resets
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)


def html_to_markdown(html_str: str) -> str:
    """Convert Confluence storage format XHTML/HTML into clean, readable Markdown.

    Handles headings, code macros, notes/warnings, tables, lists, links, and paragraphs.
    """
    if not html_str:
        return ""

    soup = BeautifulSoup(html_str, "html.parser")

    # 1. Remove non-content elements
    for s in soup(["script", "style"]):
        s.decompose()

    # 2. Confluence Structured Macros (code, note, info, warning, tip)
    for m in soup.find_all(["ac:structured-macro", "structured-macro"]):
        macro_name = (m.get("ac:name", "") or m.get("name", "")).lower()
        if macro_name == "code":
            lang = ""
            param = m.find(["ac:parameter", "parameter"], attrs={"ac:name": "language"})
            if param:
                lang = param.get_text().strip()
            body = m.find(["ac:plain-text-body", "plain-text-body"])
            code = body.get_text() if body else ""
            m.replace_with(f"\n\n```{lang}\n{code}\n```\n\n")
        elif macro_name in ("note", "info", "tip", "warning"):
            body = m.find(["ac:rich-text-body", "rich-text-body"])
            text = body.get_text().strip() if body else ""
            m.replace_with(f"\n\n> **{macro_name.upper()}**: {text}\n\n")

    # 3. Standard pre/code blocks
    for pre in soup.find_all("pre"):
        code = pre.get_text()
        pre.replace_with(f"\n\n```\n{code}\n```\n\n")

    # 4. Headings (h6 down to h1)
    for i in range(6, 0, -1):
        hashes = "#" * i
        for h in soup.find_all(f"h{i}"):
            h.replace_with(f"\n\n{hashes} {h.get_text().strip()}\n\n")

    # 5. Hyperlinks
    for a in soup.find_all("a"):
        href = a.get("href", "")
        text = a.get_text().strip() or href
        if href:
            a.replace_with(f"[{text}]({href})")

    # 6. Tables to Markdown
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text().strip().replace("\n", " ") for td in tr.find_all(["th", "td"])]
            if cells:
                rows.append("| " + " | ".join(cells) + " |")
        if rows:
            if len(rows) > 1 and table.find("th"):
                col_count = len(table.find("tr").find_all(["th", "td"]))
                divider = "| " + " | ".join(["---"] * col_count) + " |"
                rows.insert(1, divider)
            table.replace_with("\n\n" + "\n".join(rows) + "\n\n")

    # 7. Lists
    for li in soup.find_all("li"):
        li.replace_with(f"- {li.get_text().strip()}\n")

    # 8. Paragraphs and line breaks
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all("p"):
        p_text = p.get_text().strip()
        if p_text:
            p.replace_with(f"\n\n{p_text}\n\n")

    text = soup.get_text()
    # Normalize consecutive newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _build_confluence_document(
    page_data: dict[str, Any],
    content_html: str,
    base_url: str,
    server_tag: str = "default",
) -> Document:
    """Transform a raw Confluence page into a structured LlamaIndex Document."""
    page_id = str(page_data.get("id", ""))
    title = page_data.get("title", "Untitled Page")
    space_obj = page_data.get("space") or {}
    space_key = space_obj.get("key", "")
    space_name = space_obj.get("name", space_key)

    version_obj = page_data.get("version") or {}
    version_num = version_obj.get("number", 1)

    history_obj = page_data.get("history") or {}
    author_obj = version_obj.get("by") or history_obj.get("createdBy") or {}
    author_name = author_obj.get("displayName") or author_obj.get("username", "Unknown")

    updated_str = version_obj.get("when") or history_obj.get("lastUpdated", {}).get("when", "")
    updated_ts = 0.0
    if updated_str:
        try:
            updated_ts = float(dateutil.parser.parse(updated_str).timestamp())
        except Exception:
            pass

    # Construct browser web link
    webui_rel = page_data.get("_links", {}).get("webui", "")
    web_url = f"{base_url.rstrip('/')}{webui_rel}" if webui_rel else base_url

    body_markdown = html_to_markdown(content_html)
    if not body_markdown:
        body_markdown = "(Empty page content.)"

    header_lines = [
        f"# Confluence Page: {title}",
        f"**Space**: {space_key} ({space_name})" if space_name != space_key else f"**Space**: {space_key}",
        f"**Page ID**: {page_id}",
        f"**Version**: {version_num}",
        f"**Author**: {author_name}",
        f"**Last Updated**: {updated_str}",
        f"**URL**: {web_url}",
        "",
        "---",
        "",
        body_markdown,
    ]
    full_text = "\n".join(header_lines)

    doc_id = f"confluence-{server_tag}-{page_id}"
    return Document(
        text=full_text,
        id_=doc_id,
        metadata={
            "source": "confluence",
            "doc_id": doc_id,
            "page_id": page_id,
            "title": title,
            "space": space_key,
            "space_name": space_name,
            "version": version_num,
            "updated_at": updated_str,
            "updated_at_ts": updated_ts,
            "url": web_url,
            "author": author_name,
            "server": server_tag,
        },
    )


def ingest_confluence(
    space: str | None = None,
    cql: str | None = None,
    server: str | None = None,
    override_url: str | None = None,
    override_user: str | None = None,
    override_token: str | None = None,
    override_auth_method: str | None = None,
    max_results: int | None = None,
    force: bool = False,
) -> tuple[int, int]:
    """Ingest Confluence pages into the vector database with incremental skipping.

    Args:
        space (str | None): Confluence space key (e.g. 'PIPE', 'DEV').
        cql (str | None): Custom Confluence Query Language (CQL) expression.
        server (str | None): Name of the Confluence server profile in configuration.
        override_url (str | None): URL override.
        override_user (str | None): Username override.
        override_token (str | None): Token override.
        override_auth_method (str | None): Auth method override ('pat' or 'basic').
        max_results (int | None): Limit total pages to ingest.
        force (bool): If True, re-indexes all pages even if unmodified.

    Returns:
        tuple[int, int]: (newly_ingested_count, skipped_existing_count)
    """
    if not space and not cql:
        logger.error("Must provide either a Confluence --space key or a --cql expression.")
        return (0, 0)

    cfg = settings.get_confluence_config(server, space=space)
    server_tag = (server or cfg.get("server_name") or "default").strip().lower()
    cfg_url = override_url or cfg["url"]
    cfg_user = override_user or cfg["user"]
    cfg_token = override_token or cfg["token"]
    cfg_auth = override_auth_method or cfg["auth_method"]

    if not cfg_url or cfg_url == "https://confluence.example.com" or not cfg_token:
        logger.error(
            "Confluence credentials missing in configuration (url or token). "
            "Please specify --server <name> or configure [confluence_servers.<name>] in ~/.ragdoll/config.toml."
        )
        return (0, 0)

    base_url = cfg_url.rstrip("/")
    headers = {
        "Accept": "application/json",
        "User-Agent": "Ragdoll-Confluence-Ingest/1.0",
    }
    auth = None
    if cfg_auth == "pat":
        headers["Authorization"] = f"Bearer {cfg_token}"
    elif cfg_auth == "basic":
        auth = (cfg_user, cfg_token)

    # Determine REST content endpoint (/rest/api/content vs /wiki/rest/api/content)
    if "/wiki" in base_url.lower():
        content_endpoint = f"{base_url}/rest/api/content"
    else:
        content_endpoint = f"{base_url}/rest/api/content"

    chroma_col = None
    if not force:
        try:
            client = _get_client()
            chroma_col = client.get_or_create_collection(settings.collection_name)
        except Exception as e:
            logger.debug("Could not get ChromaDB collection for incremental Confluence check: %s", e)

    skipped_count = 0
    total_scanned = 0
    pages_to_fetch: list[dict[str, Any]] = []

    with requests.Session() as session:
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update(headers)
        if auth:
            session.auth = auth

        # Probe base REST content endpoint (/rest/api/content vs /wiki/rest/api/content)
        content_endpoint = f"{base_url}/rest/api/content"
        if "/wiki" not in base_url.lower():
            try:
                probe = session.get(content_endpoint, params={"limit": 1}, timeout=5)
                if probe.status_code == 404:
                    wiki_endpoint = f"{base_url}/wiki/rest/api/content"
                    probe_wiki = session.get(wiki_endpoint, params={"limit": 1}, timeout=5)
                    if probe_wiki.status_code == 200:
                        content_endpoint = wiki_endpoint
            except Exception as e:
                logger.debug("Endpoint probing notice: %s", e)

        # Space Key Auto-Resolution:
        # Users often pass the human Space Name (e.g. "Engineering") instead of the internal Space Key ("ENG").
        if space:
            rest_base = content_endpoint.rsplit("/content", 1)[0]
            try:
                sp_chk = session.get(f"{rest_base}/space/{space}", timeout=5)
                if sp_chk.status_code == 404:
                    all_sp = session.get(f"{rest_base}/space", params={"limit": 500}, timeout=10)
                    if all_sp.status_code == 200:
                        spaces_list = all_sp.json().get("results", [])
                        matched_key = None
                        for sp in spaces_list:
                            if sp.get("key", "").lower() == space.lower() or sp.get("name", "").lower() == space.lower():
                                matched_key = sp.get("key")
                                break
                        if matched_key:
                            logger.info("Resolved Confluence space '%s' -> space key '%s'", space, matched_key)
                            space = matched_key
                        else:
                            similar = [
                                f"'{s.get('key')}' ({s.get('name')})"
                                for s in spaces_list
                                if space.lower() in s.get("name", "").lower() or space.lower() in s.get("key", "").lower()
                            ]
                            if similar:
                                logger.warning("Space key '%s' not found. Did you mean: %s?", space, ", ".join(similar[:5]))
            except Exception as e:
                logger.debug("Space auto-resolution notice: %s", e)

        # ── Phase 1: Lightweight Metadata Scan ────────────────────────────────
        logger.info("Phase 1: Scanning Confluence metadata to detect new/modified pages...")
        start_at = 0
        batch_size = 50

        # Construct effective CQL query scoped properly by space if specified
        effective_cql = cql
        if space:
            clean_space = space.strip().strip('"').strip("'")
            if effective_cql:
                # If space filter is not already specified in cql, scope it to this space
                if not re.search(r"\bspace\s*(=|!=|in\b)", effective_cql, re.IGNORECASE):
                    effective_cql = f'space = "{clean_space}" AND ({effective_cql})'
            else:
                effective_cql = f'space = "{clean_space}" AND type = page'

        search_url = f"{content_endpoint}/search"
        base_params: dict[str, Any] = {"cql": effective_cql, "expand": "version,history,space"}

        while True:
            current_limit = batch_size
            if max_results is not None:
                remaining = max_results - total_scanned
                if remaining <= 0:
                    break
                current_limit = min(batch_size, remaining)

            params = {**base_params, "start": start_at, "limit": current_limit}

            try:
                resp = session.get(search_url, params=params, timeout=20)
                if resp.status_code == 404 and search_url.endswith("/search") and space:
                    logger.debug("CQL /search endpoint returned 404; falling back to /content?spaceKey=...")
                    search_url = content_endpoint
                    base_params = {"spaceKey": space, "type": "page", "expand": "version,history,space"}
                    params = {**base_params, "start": start_at, "limit": current_limit}
                    resp = session.get(search_url, params=params, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error("Failed to fetch page list from Confluence (%s): %s", search_url, e)
                break

            raw_results = data.get("results", [])
            if not raw_results:
                break

            # Client-side space validation guard:
            # Strictly verify that returned pages belong to the targeted space to prevent
            # any cross-space leakage if the remote query was underspecified or misbehaved.
            if space:
                clean_space = space.strip().strip('"').strip("'").upper()
                page_batch = []
                for p in raw_results:
                    p_space = (p.get("space", {}).get("key") or "").strip().upper()
                    if p_space and p_space != clean_space:
                        logger.debug(
                            "Filtering out page %s ('%s') belonging to space '%s' (expected '%s')",
                            p.get("id"),
                            p.get("title"),
                            p_space,
                            space,
                        )
                        continue
                    page_batch.append(p)
            else:
                page_batch = raw_results

            total_scanned += len(page_batch)

            # Query existing timestamps in ChromaDB for this batch
            batch_ids = [f"confluence-{server_tag}-{p.get('id')}" for p in page_batch]
            existing_ts_map: dict[str, float] = {}
            if not force and chroma_col is not None:
                try:
                    records = chroma_col.get(ids=batch_ids, include=["metadatas"])
                    if records and records.get("ids"):
                        for eid, emeta in zip(records["ids"], records["metadatas"]):
                            if emeta and "updated_at_ts" in emeta:
                                try:
                                    existing_ts_map[eid] = float(emeta["updated_at_ts"])
                                except (ValueError, TypeError):
                                    pass
                except Exception as e:
                    logger.debug("Could not query ChromaDB for existing Confluence pages: %s", e)

            for p in page_batch:
                page_id = str(p.get("id"))
                doc_id = f"confluence-{server_tag}-{page_id}"

                updated_str = p.get("version", {}).get("when") or p.get("history", {}).get("lastUpdated", {}).get("when", "")
                conf_ts = 0.0
                if updated_str:
                    try:
                        conf_ts = float(dateutil.parser.parse(updated_str).timestamp())
                    except Exception:
                        pass

                if not force and doc_id in existing_ts_map and conf_ts > 0 and conf_ts <= existing_ts_map[doc_id]:
                    skipped_count += 1
                else:
                    pages_to_fetch.append(p)

            logger.info(
                "Scanned %d Confluence page(s) (%d new/updated, %d up-to-date)...",
                total_scanned,
                len(pages_to_fetch),
                skipped_count,
            )

            if len(raw_results) < current_limit or ("_links" in data and "next" not in data.get("_links", {})):
                break

            start_at += len(raw_results)

        if not pages_to_fetch:
            if skipped_count > 0:
                logger.info("All %d Confluence page(s) are already up-to-date in ChromaDB.", skipped_count)
                return (0, skipped_count)
            logger.warning("No Confluence pages found matching criteria.")
            return (0, 0)

        # ── Phase 2: Fetch Storage Content for New / Modified Pages ───────────
        logger.info("Phase 2: Fetching full content for %d new/modified page(s)...", len(pages_to_fetch))
        documents: list[Document] = []

        for p in pages_to_fetch:
            page_id = str(p.get("id"))
            page_url = f"{content_endpoint}/{page_id}"
            try:
                p_resp = session.get(page_url, params={"expand": "body.storage,version,history,space"}, timeout=20)
                p_resp.raise_for_status()
                full_page = p_resp.json()
                html_body = full_page.get("body", {}).get("storage", {}).get("value", "")
                doc = _build_confluence_document(full_page, html_body, base_url, server_tag=server_tag)
                documents.append(doc)
            except Exception as e:
                logger.warning("Failed to fetch body for Confluence page %s (%s): %s", page_id, p.get("title"), e)

    if not documents:
        return (0, skipped_count)

    # ── Phase 3: Embedding and Storing in Vector DB ─────────────────────────
    logger.info("Phase 3: Indexing %d Confluence document(s) into ChromaDB...", len(documents))
    index = get_index()
    batch_size = 20
    with GracefulInterrupt() as gi:
        for i in range(0, len(documents), batch_size):
            batch = documents[i: i + batch_size]
            index.insert_nodes(batch)
            if gi.interrupted:
                break

    return (len(documents), skipped_count)
