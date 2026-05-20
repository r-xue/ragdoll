"""Semantic retriever.

Queries the vector store and returns structured search results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ragdoll.store import vectordb

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search hit.

    Attributes
    ----------
    chunk_id : str
        The chunk identifier.
    text : str
        The chunk text.
    score : float
        Similarity score (cosine distance — lower is better).
    metadata : dict
        Chunk metadata.
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

    Parameters
    ----------
    query : str
        Natural-language search query.
    top_k : int, optional
        Number of results (default: from settings).
    source_filter : str, optional
        If provided, filter by source type (``"pdf"`` or ``"jira"``).

    Returns
    -------
    list[SearchResult]
        Ranked search results.
    """
    where = None
    if source_filter:
        where = {"source": source_filter}

    results = vectordb.query(query, n_results=top_k, where=where)

    hits: list[SearchResult] = []
    if not results["ids"] or not results["ids"][0]:
        return hits

    for chunk_id, text, metadata, distance in zip(
        results["ids"][0],
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        hits.append(
            SearchResult(
                chunk_id=chunk_id,
                text=text,
                score=distance,
                metadata=metadata,
            )
        )

    logger.info("Search for %r returned %d hits.", query, len(hits))
    return hits
