"""Tests for ChromaDB vector store client instantiation."""

from unittest.mock import patch, MagicMock
from ragdoll.config import settings
from ragdoll.store.vectordb import _get_client


def test_local_chroma_client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "chroma_host", None)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    client = _get_client()
    assert client is not None


def test_remote_chroma_client(monkeypatch):
    monkeypatch.setattr(settings, "chroma_host", "http://chroma.internal")
    monkeypatch.setattr(settings, "chroma_port", 9000)
    monkeypatch.setattr(settings, "chroma_ssl", True)
    monkeypatch.setattr(settings, "chroma_auth_token", "test-token")

    with patch("chromadb.HttpClient") as mock_http_client:
        mock_http_client.return_value = MagicMock()
        client = _get_client()
        mock_http_client.assert_called_once_with(
            host="http://chroma.internal",
            port=9000,
            ssl=True,
            headers={"Authorization": "Bearer test-token"},
            tenant="default_tenant",
            database="default_database",
        )
        assert client == mock_http_client.return_value


def test_ragdoll_chroma_vector_store_upsert(tmp_path):
    import chromadb
    from llama_index.core.schema import TextNode
    from ragdoll.store.vectordb import RagdollChromaVectorStore

    client = chromadb.PersistentClient(path=str(tmp_path))
    collection = client.get_or_create_collection(name="test_collection")
    store = RagdollChromaVectorStore(chroma_collection=collection)

    node1 = TextNode(
        id_="issue-1",
        text="Initial summary text",
        metadata={"updated_at_ts": 1000.0, "status": "Open"},
        embedding=[0.1] * 384,
    )
    store.add([node1])

    records = collection.get(ids=["issue-1"], include=["documents", "metadatas"])
    assert records["ids"] == ["issue-1"]
    assert records["documents"][0] == "Initial summary text"
    assert records["metadatas"][0]["updated_at_ts"] == 1000.0
    assert records["metadatas"][0]["status"] == "Open"

    node1_updated = TextNode(
        id_="issue-1",
        text="Updated summary text with new resolution",
        metadata={"updated_at_ts": 2000.0, "status": "Resolved"},
        embedding=[0.9] * 384,
    )
    store.add([node1_updated])

    records_after = collection.get(ids=["issue-1"], include=["documents", "metadatas"])
    assert len(records_after["ids"]) == 1
    assert records_after["documents"][0] == "Updated summary text with new resolution"
    assert records_after["metadatas"][0]["updated_at_ts"] == 2000.0
    assert records_after["metadatas"][0]["status"] == "Resolved"
