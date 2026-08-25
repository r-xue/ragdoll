"""Tests for GitHub ingestion helpers."""

from ragdoll.ingest.github import _build_github_document


def test_build_github_document_issue():
    issue = {
        "number": 42,
        "title": "Fix memory leak in buffer",
        "body": "Memory increases over time during streaming.",
        "state": "open",
        "user": {"login": "alice"},
        "created_at": "2026-05-10T14:30:00Z",
        "updated_at": "2026-05-11T09:00:00Z",
    }
    comments = [
        {
            "user": {"login": "bob"},
            "created_at": "2026-05-10T15:00:00Z",
            "body": "Reproduced on Linux x86_64.",
        }
    ]
    doc = _build_github_document(issue, comments, owner="myorg", repo="myrepo")

    assert doc.id_ == "github-myorg-myrepo-42"
    assert doc.metadata["source"] == "github"
    assert doc.metadata["owner"] == "myorg"
    assert doc.metadata["repo"] == "myrepo"
    assert doc.metadata["issue_number"] == "42"
    assert doc.metadata["is_pr"] is False
    assert doc.metadata["author"] == "alice"
    assert doc.metadata["status"] == "open"
    assert doc.metadata["created_at_ts"] > 0
    assert "Title: [Issue-42] Fix memory leak in buffer" in doc.text
    assert "[bob - 2026-05-10]: Reproduced on Linux x86_64." in doc.text


def test_build_github_document_pr():
    pr = {
        "number": 101,
        "title": "Add AST-based code parser",
        "body": "Implements AST tree-sitter chunking.",
        "state": "closed",
        "user": {"login": "charlie"},
        "pull_request": {},
        "created_at": "2026-06-01T10:00:00Z",
        "updated_at": "2026-06-02T12:00:00Z",
    }
    doc = _build_github_document(pr, [], owner="org", repo="repo")
    assert doc.id_ == "github-org-repo-101"
    assert doc.metadata["is_pr"] is True
    assert "Title: [PR-101] Add AST-based code parser" in doc.text


def test_ingest_github_incremental():
    from unittest.mock import patch, MagicMock
    from ragdoll.ingest.github import ingest_github

    mock_issues = [
        {
            "number": 1,
            "title": "Up-to-date issue",
            "body": "No changes",
            "state": "open",
            "user": {"login": "alice"},
            "created_at": "2026-05-01T10:00:00Z",
            "updated_at": "2026-05-01T10:00:00Z",
            "comments": 0,
        },
        {
            "number": 2,
            "title": "New issue",
            "body": "Brand new",
            "state": "open",
            "user": {"login": "bob"},
            "created_at": "2026-05-02T10:00:00Z",
            "updated_at": "2026-05-02T10:00:00Z",
            "comments": 0,
        },
    ]

    with patch("requests.Session.get") as mock_get, \
            patch("ragdoll.ingest.github._get_client") as mock_client, \
            patch("ragdoll.ingest.github.get_index") as mock_index:

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_issues
        mock_resp.links = {}
        mock_get.return_value = mock_resp

        # Issue 1 is already in ChromaDB with same updated_at_ts
        ts_1 = 1777629600.0  # 2026-05-01T10:00:00Z approx
        mock_col = MagicMock()
        mock_col.get.return_value = {
            "ids": ["github-org-repo-1"],
            "metadatas": [{"updated_at_ts": ts_1}],
        }
        mock_client.return_value.get_or_create_collection.return_value = mock_col
        mock_index.return_value = MagicMock()

        total, new_issues, new_prs, skipped = ingest_github("org", "repo", override_url="https://api.github.com", override_token="token")
        assert total == 1
        assert new_issues == 1
        assert skipped == 1

