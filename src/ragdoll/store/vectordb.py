"""ChromaDB vector store wrapper for LlamaIndex.

Manages a local or remote ChromaDB collection for storing and querying
document chunk embeddings via LlamaIndex.
"""

from __future__ import annotations

import logging
import chromadb
from typing import Any, List
from chromadb.api import ClientAPI
from llama_index.core import VectorStoreIndex
from llama_index.core.schema import BaseNode, MetadataMode
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.vector_stores.chroma.base import MAX_CHUNK_SIZE, chunk_list, node_to_metadata_dict
from llama_index.core.storage.storage_context import StorageContext

from ragdoll.config import settings

logger = logging.getLogger(__name__)


class RagdollChromaVectorStore(ChromaVectorStore):
    """Enhanced ChromaVectorStore that uses collection.upsert instead of collection.add.

    Default LlamaIndex ChromaVectorStore calls collection.add(), which silently
    ignores nodes if their ID already exists in ChromaDB. Using upsert ensures that
    updated issues, wiki pages, pull requests, and documentation chunks overwrite
    the previous record with the new text, embedding, and updated_at_ts metadata.
    """

    def add(self, nodes: List[BaseNode], **add_kwargs: Any) -> List[str]:
        if not self._collection:
            raise ValueError("Collection not initialized")

        max_chunk_size = MAX_CHUNK_SIZE
        node_chunks = chunk_list(nodes, max_chunk_size)

        all_ids = []
        for node_chunk in node_chunks:
            embeddings = []
            metadatas = []
            ids = []
            documents = []
            for node in node_chunk:
                embeddings.append(node.get_embedding())
                metadata_dict = node_to_metadata_dict(
                    node, remove_text=True, flat_metadata=self.flat_metadata
                )
                for key in metadata_dict:
                    if metadata_dict[key] is None:
                        metadata_dict[key] = ""
                metadatas.append(metadata_dict)
                ids.append(node.node_id)
                documents.append(node.get_content(metadata_mode=MetadataMode.NONE))

            self._collection.upsert(
                embeddings=embeddings,
                ids=ids,
                metadatas=metadatas,
                documents=documents,
            )
            all_ids.extend(ids)

        return all_ids


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


def get_vector_store(name: str | None = None) -> RagdollChromaVectorStore:
    """Get the LlamaIndex ChromaVectorStore wrapper with upsert support."""
    client = _get_client()
    name = name or settings.collection_name
    chroma_collection = client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"}
    )
    return RagdollChromaVectorStore(chroma_collection=chroma_collection)


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
