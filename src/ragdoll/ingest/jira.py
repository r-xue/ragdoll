"""JIRA ingestion pipeline via LlamaIndex.

Connects to a JIRA instance, retrieves issues using JQL,
and indexes them into the vector store.
"""

import logging
from llama_index.readers.jira import JiraReader

from ragdoll.config import settings
from ragdoll.store.vectordb import get_index

logger = logging.getLogger(__name__)


def ingest_jira(jql: str = "project = CAS") -> int:
    """Fetch and ingest JIRA issues matching a JQL query.

    Args:
        jql (str): JIRA Query Language string.

    Returns:
        int: Number of chunks upserted.
    """
    if not settings.jira_url or not settings.jira_token or not settings.jira_user:
        logger.error("JIRA credentials missing in configuration.")
        return 0

    logger.info("Fetching JIRA issues using LlamaIndex JiraReader: %s", jql)
    
    # We use LlamaIndex JiraReader which automatically formats Jira tickets
    # into Document nodes.
    try:
        if settings.jira_auth_method == "pat":
            # For PAT auth, LlamaIndex expects PATauth dict and uses the URL literally.
            reader = JiraReader(
                PATauth={
                    "server_url": settings.jira_url,
                    "api_token": settings.jira_token,
                }
            )
        else:
            # For Basic auth, LlamaIndex prepends "https://" automatically,
            # so we must strip it if it's already there to prevent double https://.
            server_url = settings.jira_url
            if server_url.startswith("https://"):
                server_url = server_url[8:]
            elif server_url.startswith("http://"):
                server_url = server_url[7:]
                
            reader = JiraReader(
                email=settings.jira_user,
                api_token=settings.jira_token,
                server_url=server_url,
            )

        documents = reader.load_data(query=jql)
        
    except Exception as e:
        logger.error("Failed to fetch from JIRA: %s", e)
        return 0

    if not documents:
        logger.info("No JIRA issues found for query: %s", jql)
        return 0
        
    for doc in documents:
        doc.metadata["source"] = "jira"
        # ChromaDB requires flat metadata (only str, int, float, bool).
        # JiraReader might return lists (e.g., labels) or dicts. We must sanitize them.
        for key, value in list(doc.metadata.items()):
            if value is None:
                continue
            if isinstance(value, list):
                doc.metadata[key] = ", ".join(str(v) for v in value)
            elif not isinstance(value, (str, int, float, bool)):
                doc.metadata[key] = str(value)

    logger.info("Fetched %d JIRA documents. Indexing into vector store...", len(documents))
    
    index = get_index()
    for doc in documents:
        index.insert(doc)

    logger.info("Successfully ingested JIRA issues.")
    return len(documents)
