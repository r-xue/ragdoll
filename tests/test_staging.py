"""Tests for repository staging and directory-level source ingestion."""

from pathlib import Path
from unittest.mock import patch, MagicMock
from ragdoll.ingest.staging import stage_repositories, ingest_all_sources


def test_stage_repositories_parsing(tmp_path: Path):
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    manifest = manifests_dir / "repos.txt"
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


def test_ingest_all_sources_directory_and_manifests(tmp_path: Path):
    # 1. Setup local physical folders
    pdf_dir = tmp_path / "pdf"
    pdf_dir.mkdir()
    (pdf_dir / "doc.pdf").write_bytes(b"%PDF-1.4 dummy")

    md_dir = tmp_path / "markdown"
    md_dir.mkdir()
    (md_dir / "spec.md").write_text("# Spec\nHello world")

    # 2. Setup manifests
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    (manifests_dir / "jira.txt").write_text('primary "project = TEST"')
    (manifests_dir / "github.txt").write_text("myorg myrepo all")
    (manifests_dir / "bitbucket.txt").write_text("MYPROJ myrepo ALL")

    with patch("ragdoll.ingest.staging.ingest_pdfs") as mock_pdf, \
            patch("ragdoll.ingest.staging.get_index") as mock_index, \
            patch("ragdoll.ingest.staging.ingest_jira") as mock_jira, \
            patch("ragdoll.ingest.staging.ingest_github") as mock_github, \
            patch("ragdoll.ingest.staging.ingest_bitbucket") as mock_bitbucket:

        mock_pdf.return_value = (5, 0)
        mock_index_instance = MagicMock()
        mock_index.return_value = mock_index_instance
        mock_jira.return_value = 10
        mock_github.return_value = (3, 3, 0)
        mock_bitbucket.return_value = 4

        summary = ingest_all_sources(root_path=tmp_path)
        assert summary["pdf_documents"] == 5
        assert summary["markdown_documents"] >= 1
        assert summary["jira_tickets"] == 10
        assert summary["github_items"] == 3
        assert summary["bitbucket_prs"] == 4

        mock_jira.assert_called_once_with(jql="project = TEST", server="primary", force=False)
        mock_github.assert_called_once_with(owner="myorg", repo="myrepo", state="all", server=None, force=False)
        mock_bitbucket.assert_called_once_with(project="MYPROJ", repo="myrepo", state="ALL", server=None, force=False)


def test_stage_pdfs_download_and_cache(tmp_path: Path):
    from ragdoll.ingest.staging import stage_pdfs
    import io

    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    pdf_manifest = manifests_dir / "pdf.txt"
    pdf_manifest.write_text("""
# Test PDF manifest
https://example.com/docs/existing.pdf user_guides/existing.pdf
https://example.com/docs/new_doc.pdf memos/new_doc.pdf
""")

    target_pdf_dir = tmp_path / "pdf"
    target_pdf_dir.mkdir()
    user_guides = target_pdf_dir / "user_guides"
    user_guides.mkdir()
    (user_guides / "existing.pdf").write_bytes(b"%PDF-1.4 existing file content")

    mock_response = io.BytesIO(b"%PDF-1.4 downloaded new document content")

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response

        results = stage_pdfs(manifest_path=pdf_manifest, target_dir=target_pdf_dir)

        assert len(results) == 2
        # First file was already present locally
        assert results[0]["status"] == "Up to date"
        assert Path(results[0]["destination"]).name == "existing.pdf"

        # Second file was downloaded
        assert results[1]["status"] == "Downloaded"
        assert (target_pdf_dir / "memos" / "new_doc.pdf").is_file()
        assert (target_pdf_dir / "memos" / "new_doc.pdf").read_bytes() == b"%PDF-1.4 downloaded new document content"


def test_parse_repos_manifest_and_all_commits(tmp_path: Path):
    from ragdoll.ingest.staging import parse_repos_manifest

    manifest = tmp_path / "repos.txt"
    manifest.write_text("""
# Format: <URL> [BRANCH] [DIR] [COMMITS]
https://github.com/myorg/repo1.git main repo1 all
https://github.com/myorg/repo2.git master repo2 5000
https://github.com/myorg/repo3.git - repo3
""")

    configs = parse_repos_manifest(manifest)
    assert len(configs) == 3
    assert configs["repo1"]["all_commits"] is True
    assert configs["repo1"]["max_commits"] == 0

    assert configs["repo2"]["all_commits"] is False
    assert configs["repo2"]["max_commits"] == 5000

    assert configs["repo3"]["all_commits"] is False
    assert configs["repo3"]["max_commits"] == 2000


def test_ingest_all_sources_passes_all_commits_flag(tmp_path: Path):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    myrepo = repos_dir / "myrepo"
    myrepo.mkdir()
    (myrepo / ".git").mkdir()

    with (
        patch("ragdoll.ingest.staging.ingest_git") as mock_ingest_git,
        patch("ragdoll.ingest.staging.ingest_code") as mock_ingest_code,
    ):
        mock_ingest_code.return_value = []
        mock_ingest_git.return_value = (42, 0)

        summary = ingest_all_sources(root_path=tmp_path, all_commits=True)
        assert summary["git_commits"] == 42
        mock_ingest_git.assert_called_once_with(
            str(myrepo),
            max_commits=0,
            all_commits=True,
            force=False,
        )
