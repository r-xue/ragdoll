"""Tests for Bitbucket Server ingestion and incremental caching."""

from unittest.mock import MagicMock, patch
from ragdoll.ingest.bitbucket import _build_pr_document, ingest_bitbucket


def test_build_bitbucket_document():
    pr = {
        "id": 105,
        "title": "Fix calibration table format",
        "description": "Updates CASA calibration schema.",
        "state": "MERGED",
        "author": {"user": {"displayName": "Dr. Scientist"}},
        "createdDate": 1777629600000,
        "updatedDate": 1777716000000,
    }
    activities = [
        {
            "action": "COMMENTED",
            "comment": {
                "text": "LGTM, approved.",
                "author": {"displayName": "Reviewer A"},
                "createdDate": 1777630000000,
            },
        },
        {
            "action": "MERGED",
            "user": {"displayName": "Dr. Scientist"},
            "createdDate": 1777716000000,
        },
    ]

    doc = _build_pr_document(pr, activities, project="PIPE", repo="pipeline")
    assert doc.id_ == "bitbucket-PIPE-pipeline-105"
    assert doc.metadata["source"] == "bitbucket"
    assert doc.metadata["project"] == "PIPE"
    assert doc.metadata["repo"] == "pipeline"
    assert doc.metadata["pr_id"] == "105"
    assert doc.metadata["status"] == "MERGED"
    assert doc.metadata["author"] == "Dr. Scientist"
    assert doc.metadata["updated_at_ts"] == 1777716000.0

    assert "Title: [PR-105] Fix calibration table format" in doc.text
    assert "[Reviewer A - " in doc.text
    assert "*** [Dr. Scientist - " in doc.text
    assert "MERGED the pull request" in doc.text


def test_ingest_bitbucket_incremental():
    mock_prs = [
        {
            "id": 101,
            "title": "Up to date PR",
            "description": "Old PR",
            "state": "MERGED",
            "author": {"user": {"displayName": "Dev A"}},
            "createdDate": 1700000000000,
            "updatedDate": 1700005000000,
        },
        {
            "id": 102,
            "title": "New active PR",
            "description": "New work",
            "state": "OPEN",
            "author": {"user": {"displayName": "Dev B"}},
            "createdDate": 1700010000000,
            "updatedDate": 1700015000000,
        },
    ]

    with patch("requests.Session.get") as mock_get, \
            patch("ragdoll.ingest.bitbucket._get_client") as mock_client, \
            patch("ragdoll.ingest.bitbucket.get_index") as mock_index:

        # PR list response
        mock_resp_list = MagicMock()
        mock_resp_list.status_code = 200
        mock_resp_list.json.return_value = {"values": mock_prs, "isLastPage": True}

        # Activity response for PR 102
        mock_resp_act = MagicMock()
        mock_resp_act.status_code = 200
        mock_resp_act.json.return_value = {"values": []}

        mock_get.side_effect = [mock_resp_list, mock_resp_act]

        # PR 101 is already in ChromaDB with same updated_at_ts
        mock_col = MagicMock()
        mock_col.get.return_value = {
            "ids": ["bitbucket-PIPE-pipeline-101"],
            "metadatas": [{"updated_at_ts": 1700005000.0}],
        }
        mock_client.return_value.get_or_create_collection.return_value = mock_col
        mock_index.return_value = MagicMock()

        total, skipped = ingest_bitbucket(
            project="PIPE",
            repo="pipeline",
            override_url="https://bitbucket.example.com",
            override_token="token",
            override_auth_method="pat",
        )

        assert total == 1
        assert skipped == 1
        # mock_get should only be called twice: 1 for list of PRs, 1 for activities of PR 102 (PR 101 activities skipped!)
        assert mock_get.call_count == 2

