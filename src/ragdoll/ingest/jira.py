"""JIRA ingestion pipeline via LlamaIndex.

Connects to a JIRA instance, retrieves issues using JQL,
and indexes them into the vector store with incremental timestamp diffing.
"""

import logging
from llama_index.core import Document
from llama_index.readers.jira import JiraReader

from ragdoll.config import settings
from ragdoll.store.vectordb import get_index, _get_client

logger = logging.getLogger(__name__)


def _build_jira_document(issue, server_tag: str = "default") -> Document:
    """Transform raw JIRA Issue object into a LlamaIndex Document with server namespacing."""
    import dateutil.parser

    f = issue.fields
    summary = getattr(f, "summary", "") or ""
    description = getattr(f, "description", "") or "(No description provided.)"

    # Multi-value fields
    components = [c.name for c in (getattr(f, "components", None) or [])]
    fix_versions = [v.name for v in (getattr(f, "fixVersions", None) or [])]
    affects_versions = [v.name for v in (getattr(f, "versions", None) or [])]

    # Subtasks & links
    subtask_count = len(f.subtasks) if getattr(f, "subtasks", None) else 0
    linked = []
    for link in (getattr(f, "issuelinks", None) or []):
        if hasattr(link, "outwardIssue") and link.outwardIssue:
            linked.append(f"{link.type.outward} {link.outwardIssue.key}")
        elif hasattr(link, "inwardIssue") and link.inwardIssue:
            linked.append(f"{link.type.inward} {link.inwardIssue.key}")

    # Engagement & agile fields
    votes = f.votes.votes if getattr(f, "votes", None) else 0
    watches = f.watches.watchCount if getattr(f, "watches", None) else 0

    sprint_field = getattr(f, "sprint", None)
    sprint_name = sprint_field.name if (sprint_field and hasattr(sprint_field, "name")) else ""

    story_points = getattr(f, "story_points", None) or getattr(f, "customfield_10005", None)
    try:
        story_points_val = float(story_points) if story_points else 0.0
    except (ValueError, TypeError):
        story_points_val = 0.0

    environment = getattr(f, "environment", "") or ""
    status_name = f.status.name if getattr(f, "status", None) else "Unknown"
    issue_type = f.issuetype.name if getattr(f, "issuetype", None) else "Unknown"
    priority_name = f.priority.name if getattr(f, "priority", None) else "None"
    assignee_name = f.assignee.displayName if getattr(f, "assignee", None) else "Unassigned"
    reporter_name = f.reporter.displayName if getattr(f, "reporter", None) else "Unknown"
    project_name = f.project.name if getattr(f, "project", None) else ""
    resolution_name = f.resolution.name if getattr(f, "resolution", None) else ""
    resolution_date = getattr(f, "resolutiondate", "") or ""
    created_str = getattr(f, "created", "") or ""
    updated_str = getattr(f, "updated", "") or ""

    # Parse timestamps for numeric range filtering and incremental diffing
    created_ts = 0.0
    updated_ts = 0.0
    if created_str:
        try:
            created_ts = float(dateutil.parser.parse(created_str).timestamp())
        except Exception:
            pass
    if updated_str:
        try:
            updated_ts = float(dateutil.parser.parse(updated_str).timestamp())
        except Exception:
            pass

    # Build text blocks
    text_lines = [
        f"Server: {server_tag}",
        f"Key: {issue.key}",
        f"Summary: {summary}",
        f"Issue Type: {issue_type}",
        f"Status: {status_name}",
        f"Priority: {priority_name}",
        f"Assignee: {assignee_name}",
        f"Reporter: {reporter_name}",
        f"Created: {created_str}",
        f"Updated: {updated_str}",
        f"\nDescription:\n{description}",
    ]

    extra_lines = []
    if components:
        extra_lines.append(f"Components: {', '.join(components)}")
    if fix_versions:
        extra_lines.append(f"Fix Versions: {', '.join(fix_versions)}")
    if affects_versions:
        extra_lines.append(f"Affects Versions: {', '.join(affects_versions)}")
    if linked:
        extra_lines.append(f"Linked Issues: {', '.join(linked)}")

    # Comments
    comments_block = []
    if hasattr(f, "comment") and f.comment and hasattr(f.comment, "comments"):
        for c in f.comment.comments:
            c_author = c.author.displayName if (hasattr(c, "author") and c.author) else "Unknown"
            c_created = getattr(c, "created", "")[:10]
            c_body = getattr(c, "body", "") or ""
            comments_block.append(f"[{c_author} - {c_created}]: {c_body}")

    if comments_block:
        extra_lines.append("\n--- Comments ---")
        extra_lines.extend(comments_block)

    if extra_lines:
        text_lines.append("\n" + "\n".join(extra_lines))

    full_text = "\n".join(text_lines)

    # Flattened metadata
    metadata = {
        "source": "jira",
        "server": server_tag,
        "key": issue.key,
        "title": summary,
        "status": status_name,
        "issue_type": issue_type,
        "priority": priority_name,
        "assignee": assignee_name,
        "reporter": reporter_name,
        "project": project_name,
        "components": ", ".join(components),
        "fix_versions": ", ".join(fix_versions),
        "affects_versions": ", ".join(affects_versions),
        "resolution": resolution_name,
        "resolution_date": resolution_date,
        "subtask_count": subtask_count,
        "linked_issues": ", ".join(linked),
        "votes": votes,
        "watches": watches,
        "sprint": sprint_name,
        "story_points": story_points_val,
        "environment": environment,
        "created_at": created_str,
        "updated_at": updated_str,
        "created_at_ts": created_ts,
        "updated_at_ts": updated_ts,
    }

    if getattr(f, "labels", None):
        metadata["labels"] = ", ".join(str(l) for l in f.labels)
    else:
        metadata["labels"] = ""

    doc = Document(text=full_text, metadata=metadata)
    doc.doc_id = f"jira-{server_tag}-{issue.key}"
    return doc


def ingest_jira(
    jql: str,
    server: str | None = None,
    max_results: int | None = None,
    force: bool = False,
    override_url: str | None = None,
    override_user: str | None = None,
    override_token: str | None = None,
    override_auth_method: str | None = None,
) -> int:
    """Ingest JIRA issues with incremental timestamp-diffing and server namespacing.

    Args:
        jql (str): JIRA Query Language string.
        server (str | None): Name of the Jira server config to use.
        max_results (int | None): Maximum number of issues to ingest.
        force (bool): If True, re-indexes all matching issues even if unchanged.

    Returns:
        int: Number of chunks upserted.
    """
    import dateutil.parser

    cfg = settings.get_jira_config(server)
    server_tag = server or "default"

    cfg_url = override_url or cfg["url"]
    cfg_user = override_user or cfg["user"]
    cfg_token = override_token or cfg["token"]
    cfg_auth = override_auth_method or cfg["auth_method"]

    if not cfg_url or not cfg_token or not cfg_user:
        logger.error("JIRA credentials missing in configuration.")
        return 0

    logger.info("Connecting to JIRA [%s] for query: %s", server_tag, jql)

    try:
        if cfg_auth == "pat":
            reader = JiraReader(
                PATauth={
                    "server_url": cfg_url,
                    "api_token": cfg_token,
                }
            )
        else:
            server_url = cfg_url
            if server_url.startswith("https://"):
                server_url = server_url[8:]
            elif server_url.startswith("http://"):
                server_url = server_url[7:]

            reader = JiraReader(
                email=cfg_user,
                api_token=cfg_token,
                server_url=server_url,
            )

        # Access Chroma collection for fast metadata checking
        client = _get_client()
        chroma_col = client.get_or_create_collection(settings.collection_name)

        documents = []
        start_at = 0
        batch_size = settings.jira_batch_size or 100
        total_fetched = 0
        skipped_count = 0

        while True:
            current_batch_size = batch_size
            if max_results is not None:
                remaining = max_results - total_fetched
                if remaining <= 0:
                    break
                current_batch_size = min(batch_size, remaining)

            raw_batch = reader.jira.search_issues(jql, startAt=start_at, maxResults=current_batch_size)
            if not raw_batch:
                break

            total_fetched += len(raw_batch)

            # Query existing timestamps in bulk from ChromaDB for this batch
            batch_ids = [f"jira-{server_tag}-{issue.key}" for issue in raw_batch]
            existing_ts_map = {}
            if not force:
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
                    logger.debug("Could not retrieve existing records from ChromaDB: %s", e)

            # Compare timestamps and filter for only new/modified issues
            new_batch_docs = []
            for issue in raw_batch:
                doc_id = f"jira-{server_tag}-{issue.key}"
                updated_str = getattr(issue.fields, "updated", "") or ""
                jira_ts = 0.0
                if updated_str:
                    try:
                        jira_ts = float(dateutil.parser.parse(updated_str).timestamp())
                    except Exception:
                        pass

                # If issue exists and updated timestamp has not changed, skip re-embedding
                if not force and doc_id in existing_ts_map and jira_ts > 0 and jira_ts <= existing_ts_map[doc_id]:
                    skipped_count += 1
                    continue

                doc = _build_jira_document(issue, server_tag=server_tag)
                new_batch_docs.append(doc)

            documents.extend(new_batch_docs)

            logger.info(
                "Fetched batch of %d issue(s) (%d new/updated, %d up-to-date, total queued: %d)...",
                len(raw_batch),
                len(new_batch_docs),
                skipped_count,
                len(documents),
            )

            if len(raw_batch) < current_batch_size:
                break

            start_at += len(raw_batch)

    except Exception as e:
        logger.error("Failed to fetch from JIRA: %s", e)
        return 0

    if not documents:
        if total_fetched > 0:
            logger.info("All %d matching JIRA issues are already up-to-date in vector DB (0 re-embedded).", total_fetched)
            return total_fetched
        logger.info("No JIRA issues found for query: %s", jql)
        return 0

    logger.info("Embedding and indexing %d new/updated JIRA documents (skipped %d unchanged)...", len(documents), skipped_count)

    from rich.progress import track
    index = get_index()
    batch_embed_size = 64
    for i in track(range(0, len(documents), batch_embed_size), description="Embedding JIRA issues..."):
        batch_docs = documents[i: i + batch_embed_size]
        index.insert_nodes(batch_docs)

    logger.info("Successfully ingested %d JIRA issues into vector DB.", len(documents))
    return len(documents)
