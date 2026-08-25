"""GitHub ingestion module with incremental change detection."""

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

# Suppress internal urllib3 retry warnings
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)


def ingest_github(
    owner: str,
    repo: str,
    state: str = "all",
    server: str | None = None,
    override_url: str | None = None,
    override_token: str | None = None,
    force: bool = False,
) -> tuple[int, int, int, int]:
    """Ingest GitHub Issues and PRs into the vector database with incremental skipping.

    Args:
        owner (str): GitHub repository owner (user or organization).
        repo (str): Repository name.
        state (str): Issue state to filter (all, open, closed).
        server (str | None): Name of the github server config to use.
        override_url (str | None): URL override.
        override_token (str | None): Token override.
        force (bool): If True, re-indexes all Issues and PRs even if unmodified.

    Returns:
        tuple[int, int, int, int]: (total_new_documents, new_issue_count, new_pr_count, skipped_existing_count).
    """
    cfg = settings.get_github_config(server)

    cfg_url = override_url or cfg["url"]
    cfg_token = override_token or cfg["token"]

    if cfg_url.endswith("/"):
        cfg_url = cfg_url[:-1]

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Connection": "keep-alive",
    }
    if cfg_token:
        headers["Authorization"] = f"Bearer {cfg_token}"

    logger.info("Fetching GitHub Issues/PRs from %s for %s/%s (State: %s, force=%s)", cfg_url, owner, repo, state, force)

    issues_endpoint = f"{cfg_url}/repos/{owner}/{repo}/issues"

    chroma_col = None
    if not force:
        try:
            client = _get_client()
            chroma_col = client.get_or_create_collection(settings.collection_name)
        except Exception as e:
            logger.debug("Could not get ChromaDB collection for incremental GitHub check: %s", e)

    documents: list[Document] = []
    issue_count = 0
    pr_count = 0
    skipped_count = 0

    params = {"state": state, "per_page": 100, "page": 1}

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

        while True:
            try:
                resp = session.get(issues_endpoint, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error("Failed to fetch Issues/PRs from GitHub: %s", e)
                break

            if not data:
                break

            # Query existing timestamps in ChromaDB for this batch
            batch_ids = [f"github-{owner}-{repo}-{issue.get('number')}" for issue in data]
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
                    logger.debug("Could not query existing GitHub records from ChromaDB: %s", e)

            for issue in data:
                issue_number = issue.get("number")
                doc_id = f"github-{owner}-{repo}-{issue_number}"
                updated_at_str = issue.get("updated_at")
                updated_ts = 0.0
                if updated_at_str:
                    try:
                        updated_ts = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00")).timestamp()
                    except ValueError:
                        pass

                # Skip fetching comments and embedding if unmodified in ChromaDB
                if not force and doc_id in existing_ts_map and updated_ts > 0 and updated_ts <= existing_ts_map[doc_id]:
                    skipped_count += 1
                    continue

                is_pr = "pull_request" in issue
                if is_pr:
                    pr_count += 1
                else:
                    issue_count += 1

                # Fetch comments for new or modified issue/PR
                comments_endpoint = issue.get("comments_url")
                comments = []
                if comments_endpoint and issue.get("comments", 0) > 0:
                    try:
                        c_resp = session.get(comments_endpoint, timeout=10)
                        if c_resp.status_code == 200:
                            comments = c_resp.json()
                    except Exception as e:
                        logger.debug("Failed to fetch comments for issue %s: %s", issue_number, e)

                doc = _build_github_document(issue, comments, owner, repo)
                documents.append(doc)

            # Check for Link header to see if there is a next page
            if "next" in resp.links:
                params["page"] += 1
            else:
                break

    if not documents:
        if skipped_count > 0:
            logger.info("All %d GitHub Issues/PRs for %s/%s are already up-to-date in ChromaDB.", skipped_count, owner, repo)
            return (0, 0, 0, skipped_count)
        logger.warning("No Issues or PRs found for %s/%s.", owner, repo)
        return (0, 0, 0, 0)

    logger.info(
        "Indexing %d new/modified GitHub document(s) (%d Issues, %d Pull Requests; %d up-to-date skipped) into ChromaDB...",
        len(documents),
        issue_count,
        pr_count,
        skipped_count,
    )
    with GracefulInterrupt():
        index = get_index()
        index.insert_nodes(documents)

    return (len(documents), issue_count, pr_count, skipped_count)


def _build_github_document(issue: dict, comments: list, owner: str, repo: str) -> Document:
    """Transform GitHub Issue/PR data into a LlamaIndex Document."""
    issue_number = issue.get("number")
    title = issue.get("title", "")
    body = issue.get("body") or ""
    state = issue.get("state", "UNKNOWN")
    author_name = issue.get("user", {}).get("login", "Unknown")
    is_pr = "pull_request" in issue
    type_label = "PR" if is_pr else "Issue"

    created_at_str = issue.get("created_at")
    updated_at_str = issue.get("updated_at")

    # Parse ISO 8601 timestamps
    try:
        created_ts = datetime.fromisoformat(created_at_str.replace("Z", "+00:00")).timestamp() if created_at_str else 0
        updated_ts = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00")).timestamp() if updated_at_str else 0
        created_date = datetime.fromtimestamp(created_ts).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        created_ts = 0
        updated_ts = 0
        created_date = "Unknown Date"

    # Build main text body
    text_blocks = [
        f"Title: [{type_label}-{issue_number}] {title}",
        f"Author: {author_name}",
        f"Status: {state}",
        f"Created: {created_date}",
        f"\nDescription:",
        body or "(No description provided.)",
        "\n--- Comments & Activity ---",
    ]

    for comment in comments:
        c_body = comment.get("body", "")
        c_author = comment.get("user", {}).get("login", "Unknown")
        c_created_str = comment.get("created_at")
        try:
            c_ts = datetime.fromisoformat(c_created_str.replace("Z", "+00:00")).timestamp() if c_created_str else 0
            c_date = datetime.fromtimestamp(c_ts).strftime("%Y-%m-%d")
        except ValueError:
            c_date = "Unknown Date"

        text_blocks.append(f"[{c_author} - {c_date}]: {c_body}")

    text = "\n".join(text_blocks)

    # Build metadata
    metadata = {
        "source": "github",
        "owner": owner,
        "repo": repo,
        "issue_number": str(issue_number),
        "is_pr": is_pr,
        "author": author_name,
        "status": state,
        "title": title,
        "created_at_ts": created_ts,
        "updated_at_ts": updated_ts,
    }

    # For LlamaIndex we map Document kwargs
    doc = Document(text=text, metadata=metadata)
    doc.id_ = f"github-{owner}-{repo}-{issue_number}"

    return doc
