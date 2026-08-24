"""Tests for repository staging and directory-level source ingestion."""

from pathlib import Path
from unittest.mock import patch, MagicMock
from ragdoll.ingest.staging import stage_repositories, ingest_all_sources


def test_stage_repositories_parsing(tmp_path: Path):
    manifest = tmp_path / "repos.txt"
    manifest.write_text("""
# Test Manifest
https://github.com/myorg/service.git main service-custom
https://github.com/myorg/utils.git
""")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Cloned", stderr="")
        results = stage_repositories(manifest_path=manifest, target_dir=tmp_path / "clones")

        assert len(results) == 2
        assert results[0]["name"] == "service-custom"
        assert results[0]["branch"] == "main"
        assert results[0]["status"] == "Cloned"

        assert results[1]["name"] == "utils"
        assert results[1]["branch"] == "default"
        assert results[1]["status"] == "Cloned"


def test_ingest_all_sources_directory_detection(tmp_path: Path):
    # Setup folders
    pdf_dir = tmp_path / "pdf"
    pdf_dir.mkdir()
    (pdf_dir / "doc.pdf").write_bytes(b"%PDF-1.4 dummy")

    md_dir = tmp_path / "markdown"
    md_dir.mkdir()
    (md_dir / "spec.md").write_text("# Spec\nHello world")

    with patch("ragdoll.ingest.staging.ingest_pdfs") as mock_pdf, \
            patch("ragdoll.ingest.staging.get_index") as mock_index:
        mock_pdf.return_value = (5, 0)
        mock_index_instance = MagicMock()
        mock_index.return_value = mock_index_instance

        summary = ingest_all_sources(root_path=tmp_path)
        assert summary["pdf_documents"] == 5
        assert summary["markdown_documents"] >= 1
