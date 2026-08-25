"""Bitbucket Server (Data Center) ingestion module with incremental change detection."""

from __future__ import annotations

import logging
from datetime import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from llama_index.core import Document
from ragdoll.config import settings
from ragdoll.store.vectordb import get_index, _get_client
from ragdoll.store.safety import GracefulInterrupt

logger = logging.getLogger(__name__)

# Suppress noisy internal urllib3 retry warnings for transient connection resets
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)


def ingest_bitbucket(
    project: str,
    repo: str,
    state: str = "ALL",
    server: str | None = None,
    override_url: str | None = None,
    override_user: str | None = None,
    override_token: str | None = None,
    override_auth_method: str | None = None,
    force: bool = False,
) -> tuple[int, int]:
    """Ingest Bitbucket Server PRs into the vector database with incremental skipping.

    Args:
        project (str): Bitbucket project key.
        repo (str): Repository slug.
        state (str): PR state to filter (ALL, OPEN, MERGED, DECLINED).
        server (str | None): Name of the bitbucket server config to use.
        override_url (str | None): URL override.
        override_user (str | None): Username override.
        override_token (str | None): Token override.
        override_auth_method (str | None): Auth method override.
        force (bool): If True, re-indexes all PRs even if unmodified.

    Returns:
        tuple[int, int]: (newly_ingested_count, skipped_existing_count)
    """
    cfg = settings.get_bitbucket_config(server)

    cfg_url = override_url or cfg["url"]
    cfg_user = override_user or cfg["user"]
    cfg_token = override_token or cfg["token"]
    cfg_auth = override_auth_method or cfg["auth_method"]

    if not cfg_url or not cfg_token:
        logger.error("Bitbucket credentials missing in configuration.")
        return (0, 0)

    if cfg_url.endswith("/"):
        cfg_url = cfg_url[:-1]

    headers = {
        "Accept": "application/json",
        "Connection": "keep-alive",
    }
    if cfg_auth == "pat":
        headers["Authorization"] = f"Bearer {cfg_token}"
    elif cfg_auth == "basic" and cfg_user:
        import base64
        auth = base64.b64encode(f"{cfg_user}:{cfg_token}".encode()).decode()
        headers["Authorization"] = f"Basic {auth}"
    else:
        logger.error("Invalid auth configuration for Bitbucket.")
        return (0, 0)

    logger.info("Fetching Bitbucket PRs from %s for %s/%s (State: %s, force=%s)", cfg_url, project, repo, state, force)

    prs_endpoint = f"{cfg_url}/rest/api/1.0/projects/{project}/repos/{repo}/pull-requests"

    chroma_col = None
    if not force:
        try:
            client = _get_client()
            chroma_col = client.get_or_create_collection(settings.collection_name)
        except Exception as e:
            logger.debug("Could not get ChromaDB collection for incremental Bitbucket check: %s", e)

    documents: list[Document] = []
    skipped_count = 0
    total_scanned = 0

    params = {"state": state, "limit": 100, "start": 0}
    is_last_page = False

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

        while not is_last_page:
            try:
                resp = session.get(prs_endpoint, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error("Failed to fetch PRs from Bitbucket: %s", e)
                break

            pr_batch = data.get("values", [])
            if not pr_batch:
                break

            total_scanned += len(pr_batch)

            # Query existing timestamps in ChromaDB for this batch
            batch_ids = [f"bitbucket-{project}-{repo}-{pr.get('id')}" for pr in pr_batch]
            existing_ts_map = {}
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
                    logger.debug("Could not query existing Bitbucket records from ChromaDB: %s", e)

            for pr in pr_batch:
                pr_id = pr.get("id")
                doc_id = f"bitbucket-{project}-{repo}-{pr_id}"
                updated_ts = float(pr.get("updatedDate", 0) / 1000)

                # Skip fetching /activities and embedding if unmodified in ChromaDB
                if not force and doc_id in existing_ts_map and updated_ts > 0 and updated_ts <= existing_ts_map[doc_id]:
                    skipped_count += 1
                    continue

                # Fetch activities for new or modified PR
                activities_endpoint = f"{prs_endpoint}/{pr_id}/activities"
                activities = []
                try:
                    act_resp = session.get(activities_endpoint, timeout=10)
                    if act_resp.status_code == 200:
                        activities = act_resp.json().get("values", [])
                except Exception as e:
                    logger.debug("Failed to fetch activities for PR %s: %s", pr_id, e)

                doc = _build_pr_document(pr, activities, project, repo)
                documents.append(doc)

            is_last_page = data.get("isLastPage", True)
            if not is_last_page:
                params["start"] = data.get("nextPageStart")

    if not documents:
        if skipped_count > 0:
            logger.info("All %d Bitbucket PR(s) for %s/%s are already up-to-date in ChromaDB.", skipped_count, project, repo)
            return (0, skipped_count)
        logger.warning("No PRs found for %s/%s.", project, repo)
        return (0, 0)

    logger.info("Indexing %d new/modified Bitbucket PR document(s) into ChromaDB (%d up-to-date skipped)...", len(documents), skipped_count)
    index = get_index()
    batch_size = 50
    ingested_count = 0
    with GracefulInterrupt() as gi:
        for i in range(0, len(documents), batch_size):
            batch = documents[i : i + batch_size]
            index.insert_nodes(batch)
            ingested_count += len(batch)
            if gi.interrupted:
                break

    return (ingested_count, skipped_count)


def _build_pr_document(pr: dict, activities: list, project: str, repo: str) -> Document:
    """Transform Bitbucket PR data into a LlamaIndex Document."""
    pr_id = pr.get("id")
    title = pr.get("title", "")
    description = pr.get("description", "")
    state = pr.get("state", "UNKNOWN")
    author_dict = pr.get("author", {}).get("user", {})
    author_name = author_dict.get("displayName") or author_dict.get("name") or "Unknown"

    created_ts = pr.get("createdDate", 0) / 1000
    updated_ts = pr.get("updatedDate", 0) / 1000
    created_date = datetime.fromtimestamp(created_ts).strftime("%Y-%m-%d %H:%M")

    # Build main text body
    text_blocks = [
        f"Title: [PR-{pr_id}] {title}",
        f"Author: {author_name}",
        f"Status: {state}",
        f"Created: {created_date}",
        "\nDescription:",
        description or "(No description provided.)",
        "\n--- Comments & Activity ---",
    ]

    for act in activities:
        action = act.get("action")
        if action == "COMMENTED":
            comment = act.get("comment", {})
            c_text = comment.get("text", "")
            c_author = comment.get("author", {}).get("displayName", "Unknown")
            c_ts = comment.get("createdDate", 0) / 1000
            c_date = datetime.fromtimestamp(c_ts).strftime("%Y-%m-%d")
            text_blocks.append(f"[{c_author} - {c_date}]: {c_text}")
        elif action in ["MERGED", "DECLINED", "APPROVED"]:
            u_name = act.get("user", {}).get("displayName", "Unknown")
            a_ts = act.get("createdDate", 0) / 1000
            a_date = datetime.fromtimestamp(a_ts).strftime("%Y-%m-%d")
            text_blocks.append(f"*** [{u_name} - {a_date}] {action} the pull request ***")

    text = "\n".join(text_blocks)

    # Build metadata
    metadata = {
        "source": "bitbucket",
        "project": project,
        "repo": repo,
        "pr_id": str(pr_id),
        "author": author_name,
        "status": state,
        "title": title,
        "created_at_ts": created_ts,
        "updated_at_ts": updated_ts,
    }

    # For LlamaIndex we map Document kwargs
    doc = Document(text=text, metadata=metadata)
    doc.id_ = f"bitbucket-{project}-{repo}-{pr_id}"

    return doc
