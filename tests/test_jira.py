"""Tests for JIRA ingestion, document building, and incremental caching."""

from unittest.mock import MagicMock, patch
from ragdoll.config import settings
from ragdoll.ingest.jira import _build_jira_document, ingest_jira


def test_build_jira_document():
    """Verify JIRA issue fields and comments are structured into a LlamaIndex Document."""
    mock_issue = MagicMock()
    mock_issue.key = "PROJ-101"
    
    f = MagicMock()
    f.summary = "Fix core database connection timeout"
    f.description = "Connection pool times out after 30s."
    comp = MagicMock()
    comp.name = "Database"
    f.components = [comp]
    f.fixVersions = []
    f.versions = []
    f.subtasks = []
    f.issuelinks = []
    f.votes.votes = 2
    f.watches.watchCount = 5
    f.sprint = None
    f.story_points = 3.0
    f.environment = "Production"
    f.status.name = "Resolved"
    f.issuetype.name = "Bug"
    f.priority.name = "High"
    f.assignee.displayName = "Alice Engineer"
    f.reporter.displayName = "Bob Tester"
    f.project.name = "Core Engine"
    f.resolution.name = "Fixed"
    f.resolutiondate = "2026-03-01T10:00:00.000+0000"
    f.created = "2026-02-25T08:00:00.000+0000"
    f.updated = "2026-03-01T10:00:00.000+0000"
    f.comment.comments = []

    mock_issue.fields = f

    doc = _build_jira_document(mock_issue, server_tag="primary")
    assert doc.id_ == "jira-primary-PROJ-101"
    assert doc.metadata["source"] == "jira"
    assert doc.metadata["server"] == "primary"
    assert doc.metadata["key"] == "PROJ-101"
    assert doc.metadata["status"] == "Resolved"
    assert doc.metadata["assignee"] == "Alice Engineer"
    assert "Fix core database connection timeout" in doc.text


@patch("ragdoll.ingest.jira.get_index")
@patch("ragdoll.ingest.jira._get_client")
@patch("ragdoll.ingest.jira.JiraReader")
def test_ingest_jira_all_up_to_date(mock_reader_cls, mock_get_client, mock_get_index):
    """Verify that when all Jira issues are up-to-date, newly ingested count is 0."""
    mock_reader = MagicMock()
    mock_reader_cls.return_value = mock_reader

    # Simulate 2 scanned issues
    issue1 = MagicMock()
    issue1.key = "PROJ-1"
    issue1.fields.updated = "2026-01-01T00:00:00.000+0000"

    issue2 = MagicMock()
    issue2.key = "PROJ-2"
    issue2.fields.updated = "2026-01-02T00:00:00.000+0000"

    mock_reader.jira.search_issues.return_value = [issue1, issue2]

    # ChromaDB collection already has both with higher/equal timestamp
    mock_chroma_col = MagicMock()
    mock_chroma_col.get.return_value = {
        "ids": ["jira-primary-PROJ-1", "jira-primary-PROJ-2"],
        "metadatas": [
            {"updated_at_ts": 2000000000.0},
            {"updated_at_ts": 2000000000.0},
        ],
    }
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_chroma_col
    mock_get_client.return_value = mock_client

    with patch.object(settings, "jira_url", "https://jira.example.com"), \
         patch.object(settings, "jira_user", "tester"), \
         patch.object(settings, "jira_token", "SECRET"), \
         patch.object(settings, "jira_servers", {"primary": {"url": "https://jira.example.com", "user": "tester", "token": "SECRET"}}):
        newly_ingested, skipped = ingest_jira("project = PROJ", server="primary")

    assert newly_ingested == 0
    assert skipped == 2
    # Verify we did not call search_issues for Phase 2 full fetch
    assert mock_reader.jira.search_issues.call_count == 1
    mock_get_index.assert_not_called()
