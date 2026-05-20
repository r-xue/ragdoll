"""ChromaDB vector store wrapper for LlamaIndex.

Manages a persistent ChromaDB collection for storing and querying
document chunk embeddings via LlamaIndex.
"""

from __future__ import annotations

import logging
import chromadb
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.core.storage.storage_context import StorageContext

from ragdoll.config import settings

logger = logging.getLogger(__name__)


def _get_client() -> chromadb.PersistentClient:
    """Create a persistent ChromaDB client."""
    settings.ensure_dirs()
    return chromadb.PersistentClient(path=str(settings.chroma_dir))


def get_vector_store(name: str | None = None) -> ChromaVectorStore:
    """Get the LlamaIndex ChromaVectorStore wrapper."""
    client = _get_client()
    name = name or settings.collection_name
    chroma_collection = client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"}
    )
    return ChromaVectorStore(chroma_collection=chroma_collection)


def get_index(name: str | None = None) -> VectorStoreIndex:
    """Get the LlamaIndex VectorStoreIndex for querying and inserting."""
    vector_store = get_vector_store(name)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    return VectorStoreIndex.from_vector_store(
        vector_store=vector_store,
        storage_context=storage_context
    )


def count(name: str | None = None) -> int:
    client = _get_client()
    name = name or settings.collection_name
    return client.get_or_create_collection(name).count()


def delete_collection(name: str | None = None) -> None:
    client = _get_client()
    name = name or settings.collection_name
    client.delete_collection(name)
    logger.info("Deleted collection: %s", name)


def list_collections() -> list[str]:
    client = _get_client()
    return [c.name for c in client.list_collections()]
