"""Bitbucket Server (Data Center) ingestion module."""

import logging
from datetime import datetime
import requests

from llama_index.core import Document
from ragdoll.config import settings
from ragdoll.store.vectordb import get_index

logger = logging.getLogger(__name__)


def ingest_bitbucket(
    project: str,
    repo: str,
    state: str = "ALL",
    server: str | None = None,
    override_url: str | None = None,
    override_user: str | None = None,
    override_token: str | None = None,
    override_auth_method: str | None = None,
) -> int:
    """Ingest Bitbucket Server PRs into the vector database.

    Args:
        project (str): Bitbucket project key.
        repo (str): Repository slug.
        state (str): PR state to filter (ALL, OPEN, MERGED, DECLINED).
        server (str | None): Name of the bitbucket server config to use.

    Returns:
        int: Number of documents upserted.
    """
    cfg = settings.get_bitbucket_config(server)
    
    cfg_url = override_url or cfg["url"]
    cfg_user = override_user or cfg["user"]
    cfg_token = override_token or cfg["token"]
    cfg_auth = override_auth_method or cfg["auth_method"]

    if not cfg_url or not cfg_token:
        logger.error("Bitbucket credentials missing in configuration.")
        return 0

    if cfg_url.endswith("/"):
        cfg_url = cfg_url[:-1]

    headers = {"Accept": "application/json"}
    if cfg_auth == "pat":
        headers["Authorization"] = f"Bearer {cfg_token}"
    elif cfg_auth == "basic" and cfg_user:
        import base64
        auth = base64.b64encode(f"{cfg_user}:{cfg_token}".encode()).decode()
        headers["Authorization"] = f"Basic {auth}"
    else:
        logger.error("Invalid auth configuration for Bitbucket.")
        return 0

    logger.info("Fetching Bitbucket PRs from %s for %s/%s (State: %s)", cfg_url, project, repo, state)

    prs_endpoint = f"{cfg_url}/rest/api/1.0/projects/{project}/repos/{repo}/pull-requests"
    
    documents = []
    
    params = {"state": state, "limit": 100, "start": 0}
    is_last_page = False
    
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    with requests.Session() as session:
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[ 429, 500, 502, 503, 504 ],
            allowed_methods=["GET"]
        )
        session.mount("http://", HTTPAdapter(max_retries=retries))
        session.mount("https://", HTTPAdapter(max_retries=retries))
        session.headers.update(headers)
        
        while not is_last_page:
            try:
                resp = session.get(prs_endpoint, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error("Failed to fetch PRs: %s", e)
                break
                
            for pr in data.get("values", []):
                pr_id = pr.get("id")
                
                # Fetch activities for this PR to get comments
                activities_endpoint = f"{prs_endpoint}/{pr_id}/activities"
                try:
                    act_resp = session.get(activities_endpoint, timeout=10)
                    act_resp.raise_for_status()
                    activities = act_resp.json().get("values", [])
                except Exception as e:
                    logger.warning("Failed to fetch activities for PR %s: %s", pr_id, e)
                    activities = []
                    
                doc = _build_pr_document(pr, activities, project, repo)
                documents.append(doc)
                
            is_last_page = data.get("isLastPage", True)
            if not is_last_page:
                params["start"] = data.get("nextPageStart")
                
    if not documents:
        return 0
        
    index = get_index()
    index.insert_nodes(documents)
    return len(documents)


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
        "\n--- Comments & Activity ---"
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
