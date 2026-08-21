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
    doc = _build_github_document(issue, comments, owner="casangi", repo="radps-context")

    assert doc.id_ == "github-casangi-radps-context-42"
    assert doc.metadata["source"] == "github"
    assert doc.metadata["owner"] == "casangi"
    assert doc.metadata["repo"] == "radps-context"
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
