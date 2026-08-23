"""ChromaDB vector store wrapper for LlamaIndex.

Manages a local or remote ChromaDB collection for storing and querying
document chunk embeddings via LlamaIndex.
"""

from __future__ import annotations

import logging
import chromadb
from chromadb.api import ClientAPI
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.core.storage.storage_context import StorageContext

from ragdoll.config import settings

logger = logging.getLogger(__name__)


def _get_client() -> ClientAPI:
    """Create a ChromaDB client (either local PersistentClient or remote HttpClient)."""
    if settings.chroma_host:
        headers = None
        if settings.chroma_auth_token:
            headers = {"Authorization": f"Bearer {settings.chroma_auth_token}"}
        return chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            ssl=settings.chroma_ssl,
            headers=headers,
            tenant=settings.chroma_tenant,
            database=settings.chroma_database,
        )
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


def delete_collection(name: str | None = None, purge_storage: bool = True) -> None:
    """Delete a ChromaDB collection and optionally purge local storage to reclaim disk space."""
    import shutil
    client = _get_client()
    name = name or settings.collection_name
    try:
        client.delete_collection(name)
    except Exception as e:
        logger.debug("Collection deletion notice: %s", e)

    if not settings.chroma_host and purge_storage and settings.chroma_dir.exists():
        shutil.rmtree(settings.chroma_dir, ignore_errors=True)
        settings.ensure_dirs()

    logger.info("Deleted collection: %s (purged local storage: %s)", name, purge_storage and not settings.chroma_host)


def list_collections() -> list[str]:
    client = _get_client()
    return [c.name for c in client.list_collections()]
