"""Unit tests for Confluence ingestion and HTML storage format parsing."""

from unittest.mock import MagicMock, patch
import pytest

from ragdoll.config import settings
from ragdoll.ingest.confluence import (
    html_to_markdown,
    _build_confluence_document,
    ingest_confluence,
)


def test_html_to_markdown_formatting():
    """Verify HTML/XHTML storage format is accurately converted to Markdown."""
    sample_html = """
    <h1>Architecture Overview</h1>
    <p>This is an introductory paragraph with a <a href="https://example.com/docs">reference link</a>.</p>
    
    <h2>Code Example</h2>
    <ac:structured-macro ac:name="code">
        <ac:parameter ac:name="language">python</ac:parameter>
        <ac:plain-text-body><![CDATA[def calculate_weight():
    return 42]]></ac:plain-text-body>
    </ac:structured-macro>

    <ac:structured-macro ac:name="note">
        <ac:rich-text-body><p>Important maintenance requirement.</p></ac:rich-text-body>
    </ac:structured-macro>

    <h3>Data Matrix</h3>
    <table>
        <tr><th>Module</th><th>Status</th></tr>
        <tr><td>Ingest</td><td>Active</td></tr>
        <tr><td>Query</td><td>Verified</td></tr>
    </table>

    <ul>
        <li>First item</li>
        <li>Second item</li>
    </ul>
    <script>alert("malicious");</script>
    """
    md = html_to_markdown(sample_html)

    assert "# Architecture Overview" in md
    assert "## Code Example" in md
    assert "[reference link](https://example.com/docs)" in md
    assert "```python\ndef calculate_weight():\n    return 42\n```" in md
    assert "> **NOTE**: Important maintenance requirement." in md
    assert "| Module | Status |" in md
    assert "| Ingest | Active |" in md
    assert "- First item" in md
    assert "alert" not in md  # Scripts decomposed


def test_build_confluence_document():
    """Verify document metadata and text structuring."""
    page_data = {
        "id": "98765",
        "title": "Release Notes 2026",
        "space": {"key": "CORE", "name": "Core Platform"},
        "version": {
            "number": 4,
            "when": "2026-03-15T10:30:00.000Z",
            "by": {"displayName": "Developer One"},
        },
        "history": {
            "createdBy": {"displayName": "Original Author"},
            "lastUpdated": {"when": "2026-03-15T10:30:00.000Z"},
        },
        "_links": {
            "webui": "/spaces/CORE/pages/98765/Release+Notes+2026"
        },
    }
    content_html = "<p>All modules updated successfully.</p>"
    base_url = "https://wiki.example.com"

    doc = _build_confluence_document(page_data, content_html, base_url, server_tag="primary")

    assert doc.id_ == "confluence-primary-98765"
    assert doc.metadata["source"] == "confluence"
    assert doc.metadata["page_id"] == "98765"
    assert doc.metadata["space"] == "CORE"
    assert doc.metadata["version"] == 4
    assert doc.metadata["author"] == "Developer One"
    assert doc.metadata["url"] == "https://wiki.example.com/spaces/CORE/pages/98765/Release+Notes+2026"
    assert "# Confluence Page: Release Notes 2026" in doc.text
    assert "All modules updated successfully." in doc.text


def test_get_confluence_config():
    """Verify multi-server configuration fallback and resolution."""
    # Test default fallback
    with patch.object(settings, "confluence_token", ""), \
         patch.object(settings, "confluence_servers", {}):
        cfg = settings.get_confluence_config(None)
        assert "url" in cfg
        assert "auth_method" in cfg

    # Test named profile
    with patch.object(settings, "confluence_token", ""), \
         patch.object(
            settings,
            "confluence_servers",
            {
                "internal": {
                    "url": "https://confluence.internal.org",
                    "token": "SECRET_PAT_TOKEN",
                    "auth_method": "pat",
                    "spaces": ["CORE", "APP"],
                }
            },
         ):
        int_cfg = settings.get_confluence_config("internal")
        assert int_cfg["url"] == "https://confluence.internal.org"
        assert int_cfg["token"] == "SECRET_PAT_TOKEN"
        assert int_cfg["spaces"] == ["CORE", "APP"]

        # Test automatic resolution by space key without passing server name
        auto_cfg = settings.get_confluence_config(None, space="APP")
        assert auto_cfg["server_name"] == "internal"
        assert auto_cfg["url"] == "https://confluence.internal.org"
        assert auto_cfg["token"] == "SECRET_PAT_TOKEN"

        # Test single server resolution fallback
        single_cfg = settings.get_confluence_config(None)
        assert single_cfg["server_name"] == "internal"
        assert single_cfg["url"] == "https://confluence.internal.org"


def test_ingest_confluence_missing_parameters():
    """Verify calling without space or cql exits cleanly."""
    count, skipped = ingest_confluence(space=None, cql=None)
    assert count == 0
    assert skipped == 0


@patch("ragdoll.ingest.confluence.get_index")
@patch("ragdoll.ingest.confluence._get_client")
@patch("requests.Session")
def test_ingest_confluence_incremental_skipping(mock_session_cls, mock_get_client, mock_get_index):
    """Verify 2-phase scanning skips existing pages and only fetches new ones."""
    # Mock Chroma collection
    mock_chroma_col = MagicMock()
    mock_chroma_col.get.return_value = {
        "ids": ["confluence-default-101"],
        "metadatas": [{"updated_at_ts": 1773570600.0}],  # Match page 101 timestamp
    }
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_chroma_col
    mock_get_client.return_value = mock_client

    # Mock index
    mock_index = MagicMock()
    mock_get_index.return_value = mock_index

    # Mock HTTP Session
    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__.return_value = mock_session

    # Phase 1 response: 2 pages returned in space
    phase1_resp = MagicMock()
    phase1_resp.status_code = 200
    phase1_resp.json.return_value = {
        "results": [
            {
                "id": "101",
                "title": "Existing Up To Date Page",
                "space": {"key": "CORE", "name": "Core Space"},
                "version": {"number": 1, "when": "2026-03-15T10:30:00.000Z"},
            },
            {
                "id": "102",
                "title": "Brand New Page",
                "space": {"key": "CORE", "name": "Core Space"},
                "version": {"number": 1, "when": "2026-03-15T11:00:00.000Z"},
            },
        ]
    }

    # Phase 2 response: Full detail for page 102
    phase2_resp = MagicMock()
    phase2_resp.status_code = 200
    phase2_resp.json.return_value = {
        "id": "102",
        "title": "Brand New Page",
        "space": {"key": "CORE", "name": "Core Space"},
        "version": {"number": 1, "when": "2026-03-15T11:00:00.000Z"},
        "body": {"storage": {"value": "<p>Brand new content details.</p>"}},
        "_links": {"webui": "/pages/102"},
    }

    def mock_get(url, **kwargs):
        if "102" in url:
            return phase2_resp
        return phase1_resp

    mock_session.get.side_effect = mock_get

    with patch.object(settings, "confluence_url", "https://wiki.example.com"), \
            patch.object(settings, "confluence_token", "TEST_TOKEN"), \
            patch.object(settings, "confluence_servers", {}):
        ingested, skipped = ingest_confluence(space="CORE")

    assert skipped == 1
    assert ingested == 1
    # Check that insert_nodes was called for the 1 new page
    assert mock_index.insert_nodes.called


@patch("ragdoll.ingest.confluence.get_index")
@patch("ragdoll.ingest.confluence._get_client")
@patch("requests.Session")
def test_confluence_cql_space_scoping(mock_session_cls, mock_get_client, mock_get_index):
    """Verify that specifying space always scopes the CQL query, whether cql is provided or not."""
    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__.return_value = mock_session

    empty_resp = MagicMock()
    empty_resp.status_code = 200
    empty_resp.json.return_value = {"results": []}
    mock_session.get.return_value = empty_resp

    with patch.object(settings, "confluence_url", "https://wiki.example.com"), \
            patch.object(settings, "confluence_token", "TEST_TOKEN"), \
            patch.object(settings, "confluence_servers", {}):
        # 1. space provided with cql="type = page" -> combined
        ingest_confluence(space="DOCS", cql="type = page")
        call_params = mock_session.get.call_args[1]["params"]
        assert call_params["cql"] == 'space = "DOCS" AND (type = page)'

        # 2. space provided with cql=None -> defaults to space = "DOCS" AND type = page
        ingest_confluence(space="DOCS", cql=None)
        call_params = mock_session.get.call_args[1]["params"]
        assert call_params["cql"] == 'space = "DOCS" AND type = page'

        # 3. space already in cql -> not duplicated
        ingest_confluence(space="DOCS", cql='space = "DOCS" AND type = page')
        call_params = mock_session.get.call_args[1]["params"]
        assert call_params["cql"] == 'space = "DOCS" AND type = page'


@patch("ragdoll.ingest.confluence.get_index")
@patch("ragdoll.ingest.confluence._get_client")
@patch("requests.Session")
def test_confluence_space_client_guard(mock_session_cls, mock_get_client, mock_get_index):
    """Verify client-side guard excludes pages from unexpected spaces even if returned by API."""
    mock_chroma_col = MagicMock()
    mock_chroma_col.get.return_value = {"ids": [], "metadatas": []}
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_chroma_col
    mock_get_client.return_value = mock_client

    mock_index = MagicMock()
    mock_get_index.return_value = mock_index

    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__.return_value = mock_session

    phase1_resp = MagicMock()
    phase1_resp.status_code = 200
    phase1_resp.json.return_value = {
        "results": [
            {
                "id": "201",
                "title": "Target Space Page",
                "space": {"key": "DOCS", "name": "Documentation"},
                "version": {"number": 1, "when": "2026-03-15T10:00:00.000Z"},
            },
            {
                "id": "999",
                "title": "Leaked Space Page",
                "space": {"key": "OTHER", "name": "Other Space"},
                "version": {"number": 1, "when": "2026-03-15T10:00:00.000Z"},
            },
        ]
    }

    phase2_resp = MagicMock()
    phase2_resp.status_code = 200
    phase2_resp.json.return_value = {
        "id": "201",
        "title": "Target Space Page",
        "space": {"key": "DOCS", "name": "Documentation"},
        "version": {"number": 1, "when": "2026-03-15T10:00:00.000Z"},
        "body": {"storage": {"value": "<p>Content of target page.</p>"}},
        "_links": {"webui": "/pages/201"},
    }

    def mock_get(url, **kwargs):
        if "201" in url:
            return phase2_resp
        return phase1_resp

    mock_session.get.side_effect = mock_get

    with patch.object(settings, "confluence_url", "https://wiki.example.com"), \
            patch.object(settings, "confluence_token", "TEST_TOKEN"), \
            patch.object(settings, "confluence_servers", {}):
        ingested, skipped = ingest_confluence(space="DOCS")

    # Only 1 page (id 201) should be ingested; id 999 from OTHER should be rejected
    assert ingested == 1
    assert skipped == 0
    inserted_docs = mock_index.insert_nodes.call_args[0][0]
    assert len(inserted_docs) == 1
    assert inserted_docs[0].id_ == "confluence-default-201"


@patch("ragdoll.ingest.confluence.get_index")
@patch("ragdoll.ingest.confluence._get_client")
@patch("requests.Session")
def test_confluence_space_resolution_with_cql(mock_session_cls, mock_get_client, mock_get_index):
    """Verify human space name resolves to space key even when cql filter is specified."""
    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__.return_value = mock_session

    def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "/space/Engineering" in url:
            resp.status_code = 404
            return resp
        elif url.endswith("/space"):
            resp.json.return_value = {
                "results": [
                    {"key": "ENG", "name": "Engineering"},
                    {"key": "DOCS", "name": "Documentation"},
                ]
            }
            return resp
        elif "/search" in url:
            resp.json.return_value = {"results": []}
            return resp
        return resp

    mock_session.get.side_effect = mock_get

    with patch.object(settings, "confluence_url", "https://wiki.example.com"), \
            patch.object(settings, "confluence_token", "TEST_TOKEN"), \
            patch.object(settings, "confluence_servers", {}):
        ingest_confluence(space="Engineering", cql="type = page")

        # The query should resolve "Engineering" -> "ENG" and scope CQL
        call_params = mock_session.get.call_args[1]["params"]
        assert call_params["cql"] == 'space = "ENG" AND (type = page)'
