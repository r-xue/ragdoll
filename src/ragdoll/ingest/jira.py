"""JIRA ticket ingestion.

Fetches issues from an on-prem (or cloud) JIRA instance via the REST API
and normalises them into Document records for the RAG pipeline.
"""

from __future__ import annotations

import logging

from jira import JIRA

from ragdoll.config import settings
from ragdoll.ingest.pdf import Document  # reuse the shared Document dataclass

logger = logging.getLogger(__name__)


def _connect() -> JIRA:
    """Create an authenticated JIRA client from settings.

    Supports two auth modes (controlled by ``jira_auth_method``):

    - ``"pat"`` (default): Personal Access Token for JIRA Data Center.
      Uses Bearer token auth — only the token is needed, no username.
    - ``"basic"``: Username + API token for JIRA Cloud.
    """
    # Default timeout: 30 seconds for connections, 60 seconds for reads
    options = {
        "server": settings.jira_url,
        "timeout": (30, 60),
    }

    if not settings.jira_token:
        logger.warning("No JIRA token configured — attempting anonymous access.")
        return JIRA(options)

    method = settings.jira_auth_method.lower()

    if method == "pat":
        # JIRA Data Center Personal Access Token → Bearer header.
        logger.info("Connecting to JIRA with PAT auth.")
        return JIRA(options, token_auth=settings.jira_token)
    elif method == "basic":
        # JIRA Cloud: username + API token → Basic auth.
        logger.info("Connecting to JIRA with basic auth.")
        return JIRA(options, basic_auth=(settings.jira_user, settings.jira_token))
    else:
        raise ValueError(
            f"Unknown jira_auth_method: {method!r}. Use 'pat' or 'basic'."
        )


def _issue_to_text(issue) -> str:
    """Convert a JIRA issue object into a structured text representation.

    The text is formatted to preserve the most important fields for
    retrieval and summarization.
    """
    fields = issue.fields
    parts = [
        f"# {issue.key}: {fields.summary}",
        "",
        f"**Status:** {fields.status}",
        f"**Type:** {fields.issuetype}",
        f"**Priority:** {getattr(fields, 'priority', 'N/A')}",
        f"**Assignee:** {getattr(fields, 'assignee', 'Unassigned')}",
        f"**Reporter:** {getattr(fields, 'reporter', 'Unknown')}",
        f"**Created:** {fields.created}",
        f"**Updated:** {fields.updated}",
    ]

    # Components
    components = getattr(fields, "components", [])
    if components:
        parts.append(f"**Components:** {', '.join(c.name for c in components)}")

    # Labels
    labels = getattr(fields, "labels", [])
    if labels:
        parts.append(f"**Labels:** {', '.join(labels)}")

    # Fix versions
    fix_versions = getattr(fields, "fixVersions", [])
    if fix_versions:
        parts.append(f"**Fix Versions:** {', '.join(v.name for v in fix_versions)}")

    # Description
    description = getattr(fields, "description", None)
    if description:
        parts.extend(["", "## Description", "", description])

    # Comments
    comments = issue.fields.comment.comments if hasattr(fields, "comment") else []
    if comments:
        parts.extend(["", "## Comments", ""])
        for comment in comments:
            author = getattr(comment, "author", "Unknown")
            parts.append(f"**{author}** ({comment.created}):")
            parts.append(comment.body)
            parts.append("")

    return "\n".join(parts)


def ingest_jira(
    jql: str,
    max_results: int | None = None,
) -> list[Document]:
    """Fetch JIRA issues matching a JQL query and return Documents.

    Parameters
    ----------
    jql : str
        JQL query string (e.g. ``"project = CAS AND updated >= -30d"``).
    max_results : int, optional
        Maximum number of issues to fetch.  ``None`` means fetch all.

    Returns
    -------
    list[Document]
        One Document per JIRA issue.
    """
    client = _connect()
    logger.info("Fetching JIRA issues: %s", jql)

    documents: list[Document] = []
    start_at = 0
    batch = settings.jira_batch_size
    total_fetched = 0

    while True:
        issues = client.search_issues(
            jql,
            startAt=start_at,
            maxResults=batch,
            fields="*all",
        )

        if not issues:
            break

        for issue in issues:
            text = _issue_to_text(issue)
            assignee = getattr(issue.fields, "assignee", None)
            reporter = getattr(issue.fields, "reporter", None)
            doc = Document(
                doc_id=f"jira:{issue.key}",
                text=text,
                metadata={
                    "source": "jira",
                    "key": issue.key,
                    "summary": str(issue.fields.summary),
                    "status": str(issue.fields.status),
                    "type": str(issue.fields.issuetype),
                    "project": issue.key.rsplit("-", 1)[0],
                    "created": str(issue.fields.created),
                    "updated": str(issue.fields.updated),
                    "assignee": str(assignee) if assignee else "Unassigned",
                    "reporter": str(reporter) if reporter else "Unknown",
                },
            )
            documents.append(doc)

        total_fetched += len(issues)
        logger.info("Fetched %d issues so far…", total_fetched)

        if max_results and total_fetched >= max_results:
            documents = documents[:max_results]
            break

        if len(issues) < batch:
            break  # no more pages

        start_at += batch

    logger.info("Ingested %d JIRA issues.", len(documents))
    return documents
