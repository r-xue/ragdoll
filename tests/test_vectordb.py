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
