"""Semantic retriever via LlamaIndex.

Queries the vector store and returns structured search results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from llama_index.core.retrievers import VectorIndexAutoRetriever
from llama_index.core.vector_stores.types import MetadataInfo, VectorStoreInfo
from llama_index.core.schema import NodeWithScore

from ragdoll.store.vectordb import get_index
from ragdoll.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search hit.

    Attributes:
        chunk_id (str): The chunk identifier.
        text (str): The chunk text.
        score (float): Similarity score (cosine distance — lower is better).
        metadata (dict): Chunk metadata.
    """

    chunk_id: str
    text: str
    score: float
    metadata: dict = field(default_factory=dict)


def search(
    query: str,
    top_k: int | None = None,
    source_filter: str | None = None,
) -> list[SearchResult]:
    """Perform semantic search over the indexed documents.

    Args:
        query (str): Natural-language search query.
        top_k (int, optional): Number of results (default: from settings).
        source_filter (str, optional): If provided, filter by source type (``"pdf"`` or ``"jira"``).

    Returns:
        list[SearchResult]: Ranked search results.
    """
    index = get_index()
    n = top_k or settings.top_k

    # Define metadata fields for the auto-retriever so it knows how to filter
    vector_store_info = VectorStoreInfo(
        content_info='Jira tickets and PDF technical documentation. For date filtering, ONLY use < or > on the created_at_ts and updated_at_ts float timestamp fields (convert user dates to Unix timestamps). DO NOT use string date fields.',
        metadata_info=[
            MetadataInfo(name='source', type='str', description="Source of the data ('jira' or 'pdf')"),
            MetadataInfo(name='key', type='str', description='JIRA issue key (e.g. PIPE-1234)'),
            MetadataInfo(name='status', type='str', description='Status of the Jira ticket'),
            MetadataInfo(name='project', type='str', description='Project name for the Jira ticket'),
            MetadataInfo(name='assignee', type='str', description='Assignee of the Jira ticket'),
            MetadataInfo(name='reporter', type='str', description='Reporter who created the ticket'),
            MetadataInfo(name='issue_type', type='str', description='Issue type (Bug, Story, Task, Epic, etc.)'),
            MetadataInfo(name='priority', type='str', description='Priority level (Critical, Major, Minor, etc.)'),
            MetadataInfo(name='components', type='str', description='Comma-separated JIRA component names'),
            MetadataInfo(name='fix_versions', type='str', description='Comma-separated target fix version names'),
            MetadataInfo(name='affects_versions', type='str', description='Comma-separated affected version names'),
            MetadataInfo(name='resolution', type='str',
                         description='Resolution status (Fixed, Won\'t Fix, Duplicate, etc.)'),
            MetadataInfo(name='labels', type='str', description='Comma-separated labels'),
            MetadataInfo(name='linked_issues', type='str',
                         description='Comma-separated linked issue keys and relationship types'),
            MetadataInfo(name='sprint', type='str', description='Sprint name'),
            MetadataInfo(name='created_at_ts', type='float', description='Unix timestamp of when the ticket was created'),
            MetadataInfo(name='updated_at_ts', type='float', description='Unix timestamp of when the ticket was last updated'),
        ]
    )

    retriever = VectorIndexAutoRetriever(
        index,
        vector_store_info=vector_store_info,
        similarity_top_k=n,
        empty_query_info_yields_all_kwargs=True
    )

    # Retrieve nodes using LlamaIndex
    try:
        nodes: list[NodeWithScore] = retriever.retrieve(query)
    except Exception as e:
        logger.warning("LLM auto-retriever failed (%s). Falling back to basic semantic search.", type(e).__name__)
        fallback_retriever = index.as_retriever(similarity_top_k=n)
        nodes = fallback_retriever.retrieve(query)

    # In LlamaIndex, the query engine auto-retriever can't apply strict manual filters on top
    # easily in the simple retrieve call without building a query bundle, but we can manually
    # post-filter if a hard source_filter is provided (for simple cases).

    hits: list[SearchResult] = []
    for node_with_score in nodes:
        node = node_with_score.node
        meta = node.metadata

        if source_filter and meta.get("source") != source_filter:
            continue

        hits.append(
            SearchResult(
                chunk_id=node.node_id,
                text=node.text,
                score=node_with_score.score or 0.0,
                metadata=meta,
            )
        )

    logger.info("Search for %r returned %d hits.", query, len(hits))
    return hits
