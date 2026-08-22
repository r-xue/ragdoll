"""Semantic retriever via LlamaIndex.

Queries the vector store and returns structured search results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

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
        source_filter (str, optional): If provided, filter by source type (``"pdf"``, ``"jira"``, ``"code"``, etc.).

    Returns:
        list[SearchResult]: Ranked search results.
    """
    index = get_index()
    n = top_k or settings.top_k

    # Direct vector retrieval: sub-second similarity search against ChromaDB
    retriever = index.as_retriever(similarity_top_k=n)
    nodes: list[NodeWithScore] = retriever.retrieve(query)

    hits: list[SearchResult] = []
    for node_with_score in nodes:
        node = node_with_score.node
        meta = node.metadata or {}

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
