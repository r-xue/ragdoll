"""Tests for incremental PDF ingestion."""

from pathlib import Path
from unittest.mock import patch, MagicMock
from ragdoll.ingest.pdf import ingest_pdfs, _compute_sha256


def test_compute_sha256(tmp_path: Path):
    sample = tmp_path / "doc.pdf"
    sample.write_bytes(b"%PDF-1.4 sample content")
    h1 = _compute_sha256(sample)
    assert len(h1) == 64

    # Different content produces different hash
    sample.write_bytes(b"%PDF-1.4 modified content")
    h2 = _compute_sha256(sample)
    assert h1 != h2


def test_incremental_pdf_skipping(tmp_path: Path):
    doc_path = tmp_path / "report.pdf"
    doc_path.write_bytes(b"%PDF-1.4 initial content")
    expected_hash = _compute_sha256(doc_path)

    # 1. First run: No existing records in ChromaDB -> file is indexed
    with patch("ragdoll.ingest.pdf._get_client") as mock_get_client, \
            patch("ragdoll.ingest.pdf.SimpleDirectoryReader") as mock_reader, \
            patch("ragdoll.ingest.pdf.get_index") as mock_get_index:

        mock_col = MagicMock()
        mock_col.get.return_value = {"metadatas": []}
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_col
        mock_get_client.return_value = mock_client

        mock_doc = MagicMock()
        mock_doc.metadata = {}
        mock_reader_inst = MagicMock()
        mock_reader_inst.load_data.return_value = [mock_doc]
        mock_reader.return_value = mock_reader_inst

        new_count, skipped_count = ingest_pdfs(tmp_path)
        assert new_count == 1
        assert skipped_count == 0

    # 2. Second run: ChromaDB already has the same file_path and file_hash -> file is skipped
    with patch("ragdoll.ingest.pdf._get_client") as mock_get_client, \
            patch("ragdoll.ingest.pdf.SimpleDirectoryReader") as mock_reader, \
            patch("ragdoll.ingest.pdf.get_index") as mock_get_index:

        mock_col = MagicMock()
        mock_col.get.return_value = {
            "metadatas": [
                {
                    "source": "pdf",
                    "file_path": str(doc_path.resolve()),
                    "file_hash": expected_hash,
                }
            ]
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_col
        mock_get_client.return_value = mock_client

        new_count, skipped_count = ingest_pdfs(tmp_path)
        assert new_count == 0
        assert skipped_count == 1
        # SimpleDirectoryReader should NOT even be instantiated
        mock_reader.assert_not_called()
