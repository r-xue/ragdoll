"""ChromaDB vector store wrapper.

Manages a persistent ChromaDB collection for storing and querying
document chunk embeddings.
"""

from __future__ import annotations

import logging

import chromadb

from ragdoll.config import settings
from ragdoll.ingest.chunker import Chunk
from ragdoll.llm.ollama import embed

logger = logging.getLogger(__name__)


def _get_client() -> chromadb.PersistentClient:
    """Create a persistent ChromaDB client."""
    settings.ensure_dirs()
    return chromadb.PersistentClient(path=str(settings.chroma_dir))


def get_collection(
    name: str | None = None,
) -> chromadb.Collection:
    """Get (or create) the named ChromaDB collection.

    Parameters
    ----------
    name : str, optional
        Collection name (default: from settings).

    Returns
    -------
    chromadb.Collection
    """
    client = _get_client()
    name = name or settings.collection_name
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def upsert_chunks(
    chunks: list[Chunk],
    collection_name: str | None = None,
    batch_size: int = 64,
) -> int:
    """Embed and upsert chunks into ChromaDB.

    Parameters
    ----------
    chunks : list[Chunk]
        Chunks to store.
    collection_name : str, optional
        Target collection.
    batch_size : int
        Number of chunks to embed per API call.

    Returns
    -------
    int
        Number of chunks upserted.
    """
    if not chunks:
        return 0

    collection = get_collection(collection_name)
    total = 0
    skipped = 0

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c.text for c in batch]
        ids = [c.chunk_id for c in batch]
        metadatas = [c.metadata for c in batch]

        try:
            # Compute embeddings via Ollama.
            embeddings = embed(texts)

            collection.upsert(
                ids=ids,
                documents=texts,
                embeddings=embeddings,
                metadatas=metadatas,
            )
            total += len(batch)
        except Exception:
            logger.exception(
                "Failed to embed/upsert batch %d–%d (skipping %d chunks)",
                i, i + len(batch), len(batch),
            )
            skipped += len(batch)
            continue

        logger.info("Upserted %d / %d chunks.", total, len(chunks))

    if skipped:
        logger.warning("Skipped %d chunks due to errors.", skipped)

    return total


def query(
    query_text: str,
    n_results: int | None = None,
    collection_name: str | None = None,
    where: dict | None = None,
) -> dict:
    """Query the vector store with a natural-language query.

    Parameters
    ----------
    query_text : str
        The search query.
    n_results : int, optional
        Number of results to return (default: from settings).
    collection_name : str, optional
        Collection to search.
    where : dict, optional
        Optional metadata filter for ChromaDB.

    Returns
    -------
    dict
        ChromaDB query result with keys: ``ids``, ``documents``,
        ``metadatas``, ``distances``.
    """
    collection = get_collection(collection_name)
    n = n_results or settings.top_k

    # Embed the query text.
    query_embedding = embed([query_text])[0]

    kwargs: dict = {
        "query_embeddings": [query_embedding],
        "n_results": n,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where

    return collection.query(**kwargs)


def count(collection_name: str | None = None) -> int:
    """Return the number of items in the collection."""
    return get_collection(collection_name).count()


def delete_collection(name: str | None = None) -> None:
    """Delete a collection entirely."""
    client = _get_client()
    name = name or settings.collection_name
    client.delete_collection(name)
    logger.info("Deleted collection: %s", name)


def list_collections() -> list[str]:
    """List all collection names."""
    client = _get_client()
    return [c.name for c in client.list_collections()]
