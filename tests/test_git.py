"""Tests for git commit history ingestion."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from ragdoll.ingest.git import ingest_git


@pytest.fixture
def temp_git_repo(tmp_path: Path):
    """Create a sample git repository with multiple commits and a branch."""
    repo = tmp_path / "test_repo"
    repo.mkdir()

    def git_run(*args):
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=True,
        )

    git_run("init", "-b", "main")
    git_run("config", "user.name", "Test Committer")
    git_run("config", "user.email", "tester@example.com")

    # Commit 1
    (repo / "file1.txt").write_text("initial version")
    git_run("add", "file1.txt")
    git_run("commit", "-m", "feat: initial commit")

    # Commit 2
    (repo / "file2.txt").write_text("second file")
    git_run("add", "file2.txt")
    git_run("commit", "-m", "fix: bug in calculation")

    # Branch and Commit 3
    git_run("checkout", "-b", "feature-branch")
    (repo / "file3.txt").write_text("feature file")
    git_run("add", "file3.txt")
    git_run("commit", "-m", "feat: add feature file")

    git_run("checkout", "main")
    return repo


def test_ingest_git_basic_and_incremental(temp_git_repo: Path):
    mock_chroma_col = MagicMock()
    mock_chroma_col.get.return_value = {"ids": []}

    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_chroma_col

    mock_index = MagicMock()

    with patch("ragdoll.ingest.git._get_client", return_value=mock_client), \
         patch("ragdoll.ingest.git.get_index", return_value=mock_index):

        # First run: All 3 commits should be new
        new_count, skipped_count = ingest_git(temp_git_repo, max_commits=2000)
        assert new_count == 3
        assert skipped_count == 0
        assert mock_index.insert_nodes.call_count >= 1
        inserted_nodes = []
        for call in mock_index.insert_nodes.call_args_list:
            inserted_nodes.extend(call.args[0])
        assert len(inserted_nodes) == 3
        assert all(n.id_.startswith("git-test_repo-") for n in inserted_nodes)

        # Second run: All 3 commits exist in ChromaDB, so they should be skipped
        inserted_ids = [n.id_ for n in inserted_nodes]
        mock_chroma_col.get.return_value = {"ids": inserted_ids}
        mock_index.reset_mock()

        new_count_2, skipped_count_2 = ingest_git(temp_git_repo, max_commits=2000)
        assert new_count_2 == 0
        assert skipped_count_2 == 3
        assert mock_index.insert_nodes.call_count == 0

        # Third run with force=True: Re-index all 3 commits
        new_count_3, skipped_count_3 = ingest_git(temp_git_repo, max_commits=2000, force=True)
        assert new_count_3 == 3
        assert skipped_count_3 == 0
        assert mock_index.insert_nodes.call_count >= 1


def test_ingest_git_max_commits_limit(temp_git_repo: Path):
    mock_chroma_col = MagicMock()
    mock_chroma_col.get.return_value = {"ids": []}

    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_chroma_col

    mock_index = MagicMock()

    with patch("ragdoll.ingest.git._get_client", return_value=mock_client), \
         patch("ragdoll.ingest.git.get_index", return_value=mock_index):

        new_count, skipped_count = ingest_git(temp_git_repo, max_commits=2)
        assert new_count == 2
        assert mock_index.insert_nodes.call_count >= 1


def test_ingest_git_invalid_repo(tmp_path: Path):
    empty_dir = tmp_path / "not_git"
    empty_dir.mkdir()
    new_count, skipped_count = ingest_git(empty_dir)
    assert new_count == 0
    assert skipped_count == 0
