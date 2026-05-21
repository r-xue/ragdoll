"""JIRA ingestion pipeline via LlamaIndex.

Connects to a JIRA instance, retrieves issues using JQL,
and indexes them into the vector store.
"""

import logging
from llama_index.readers.jira import JiraReader

from ragdoll.config import settings
from ragdoll.store.vectordb import get_index

logger = logging.getLogger(__name__)


def ingest_jira(
    jql: str,
    server: str | None = None,
    override_url: str | None = None,
    override_user: str | None = None,
    override_token: str | None = None,
    override_auth_method: str | None = None,
) -> int:
    """Ingest JIRA issues based on a JQL query.

    Args:
        jql (str): JIRA Query Language string.
        server (str | None): Name of the Jira server config to use.

    Returns:
        int: Number of chunks upserted.
    """
    cfg = settings.get_jira_config(server)
    
    # Apply CLI overrides if present
    cfg_url = override_url or cfg["url"]
    cfg_user = override_user or cfg["user"]
    cfg_token = override_token or cfg["token"]
    cfg_auth = override_auth_method or cfg["auth_method"]

    if not cfg_url or not cfg_token or not cfg_user:
        logger.error("JIRA credentials missing in configuration.")
        return 0

    logger.info("Fetching JIRA issues using LlamaIndex JiraReader: %s", jql)

    # We use LlamaIndex JiraReader which automatically formats Jira tickets
    # into Document nodes.
    try:
        if cfg_auth == "pat":
            # For PAT auth, LlamaIndex expects PATauth dict and uses the URL literally.
            reader = JiraReader(
                PATauth={
                    "server_url": cfg_url,
                    "api_token": cfg_token,
                }
            )
        else:
            # For Basic auth, LlamaIndex prepends "https://" automatically,
            # so we must strip it if it's already there to prevent double https://.
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

        documents = reader.load_data(query=jql)

        # JiraReader doesn't extract components or fix_versions.
        # Re-fetch them from the raw JIRA API so we can store them.
        issues_by_id = {}
        for issue in reader.jira.search_issues(jql, maxResults=len(documents)):
            issues_by_id[issue.id] = issue

    except Exception as e:
        logger.error('Failed to fetch from JIRA: %s', e)
        return 0

    if not documents:
        logger.info('No JIRA issues found for query: %s', jql)
        return 0

    for doc in documents:
        doc.metadata['source'] = 'jira'

        # Enrich with fields that JiraReader does not extract natively.
        raw_issue = issues_by_id.get(doc.doc_id)
        if raw_issue:
            f = raw_issue.fields
            doc.metadata['key'] = raw_issue.key

            # Multi-value fields → comma-separated strings
            components = [c.name for c in (f.components or [])]
            fix_versions = [v.name for v in (f.fixVersions or [])]
            affects_versions = [v.name for v in (getattr(f, 'versions', None) or [])]

            doc.metadata['components'] = ', '.join(components) if components else ''
            doc.metadata['fix_versions'] = ', '.join(fix_versions) if fix_versions else ''
            doc.metadata['affects_versions'] = ', '.join(affects_versions) if affects_versions else ''

            # Resolution
            doc.metadata['resolution'] = f.resolution.name if f.resolution else ''
            doc.metadata['resolution_date'] = f.resolutiondate or ''

            # Subtasks & links
            doc.metadata['subtask_count'] = len(f.subtasks) if f.subtasks else 0
            linked = []
            for link in (f.issuelinks or []):
                if hasattr(link, 'outwardIssue') and link.outwardIssue:
                    linked.append(f'{link.type.outward} {link.outwardIssue.key}')
                elif hasattr(link, 'inwardIssue') and link.inwardIssue:
                    linked.append(f'{link.type.inward} {link.inwardIssue.key}')
            doc.metadata['linked_issues'] = ', '.join(linked) if linked else ''

            # Engagement metrics
            doc.metadata['votes'] = f.votes.votes if f.votes else 0
            doc.metadata['watches'] = f.watches.watchCount if f.watches else 0

            # Sprint (Jira Software agile field, may not exist)
            sprint_field = getattr(f, 'sprint', None)
            if sprint_field and hasattr(sprint_field, 'name'):
                doc.metadata['sprint'] = sprint_field.name
            else:
                doc.metadata['sprint'] = ''

            # Story points (custom field, commonly customfield_10005 or 10028)
            story_points = getattr(f, 'story_points', None) or getattr(f, 'customfield_10005', None)
            try:
                doc.metadata['story_points'] = float(story_points) if story_points else 0.0
            except (ValueError, TypeError):
                doc.metadata['story_points'] = 0.0

            # Environment
            doc.metadata['environment'] = f.environment or ''

            # Append structured block to document text for semantic search.
            extra_lines = []
            if components:
                extra_lines.append(f'Components: {", ".join(components)}')
            if fix_versions:
                extra_lines.append(f'Fix Versions: {", ".join(fix_versions)}')
            if affects_versions:
                extra_lines.append(f'Affects Versions: {", ".join(affects_versions)}')
            if linked:
                extra_lines.append(f'Linked Issues: {", ".join(linked)}')
            if extra_lines:
                doc.set_content(doc.get_content() + '\n' + '\n'.join(extra_lines))

        # ChromaDB requires flat metadata (only str, int, float, bool).
        # JiraReader might return lists (e.g., labels) or dicts. We must sanitize them.
        import dateutil.parser
        
        for key, value in list(doc.metadata.items()):
            if value is None:
                doc.metadata[key] = ''
                continue
            if isinstance(value, list):
                doc.metadata[key] = ', '.join(str(v) for v in value)
            elif not isinstance(value, (str, int, float, bool)):
                doc.metadata[key] = str(value)
                
            # Parse created_at / updated_at into floats for vectorDB inequality filtering
            if key in ('created_at', 'updated_at') and isinstance(doc.metadata[key], str) and doc.metadata[key]:
                try:
                    dt = dateutil.parser.parse(doc.metadata[key])
                    doc.metadata[f'{key}_ts'] = float(dt.timestamp())
                except Exception:
                    pass

    logger.info("Fetched %d JIRA documents. Indexing into vector store...", len(documents))

    from rich.progress import track
    index = get_index()
    for doc in track(documents, description="Embedding JIRA issues..."):
        index.insert(doc)

    logger.info("Successfully ingested JIRA issues.")
    return len(documents)
