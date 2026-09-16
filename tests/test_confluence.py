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
    """Verify that specifying space queries /content directly for simple page ingestion and scopes CQL for custom filters."""
    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__.return_value = mock_session

    empty_resp = MagicMock()
    empty_resp.status_code = 200
    empty_resp.json.return_value = {"results": []}
    mock_session.get.return_value = empty_resp

    with patch.object(settings, "confluence_url", "https://wiki.example.com"), \
            patch.object(settings, "confluence_token", "TEST_TOKEN"), \
            patch.object(settings, "confluence_servers", {}):
        # 1. space provided with cql="type = page" -> direct /content endpoint with spaceKey and type
        ingest_confluence(space="DOCS", cql="type = page")
        call_params = mock_session.get.call_args[1]["params"]
        assert call_params["spaceKey"] == "DOCS"
        assert call_params["type"] == "page"

        # 2. space provided with cql=None -> defaults to direct /content endpoint with spaceKey and type
        ingest_confluence(space="DOCS", cql=None)
        call_params = mock_session.get.call_args[1]["params"]
        assert call_params["spaceKey"] == "DOCS"
        assert call_params["type"] == "page"

        # 3. space provided with custom CQL -> scoped via CQL search endpoint
        ingest_confluence(space="DOCS", cql="label = 'release'")
        call_params = mock_session.get.call_args[1]["params"]
        assert call_params["cql"] == 'space = "DOCS" AND (label = \'release\')'

        # 4. space already in custom CQL -> not duplicated
        ingest_confluence(space="DOCS", cql='space = "DOCS" AND label = \'release\'')
        call_params = mock_session.get.call_args[1]["params"]
        assert call_params["cql"] == 'space = "DOCS" AND label = \'release\''


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
def test_confluence_space_with_custom_cql(mock_session_cls, mock_get_client, mock_get_index):
    """Verify specifying space with custom CQL routes to search endpoint and scopes query."""
    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__.return_value = mock_session

    empty_resp = MagicMock()
    empty_resp.status_code = 200
    empty_resp.json.return_value = {"results": []}
    mock_session.get.return_value = empty_resp

    with patch.object(settings, "confluence_url", "https://wiki.example.com"), \
            patch.object(settings, "confluence_token", "TEST_TOKEN"), \
            patch.object(settings, "confluence_servers", {}):
        ingest_confluence(space="ENG", cql="label = 'release'")

        call_params = mock_session.get.call_args[1]["params"]
        assert call_params["cql"] == 'space = "ENG" AND (label = \'release\')'


@patch("ragdoll.ingest.confluence.get_index")
@patch("ragdoll.ingest.confluence._get_client")
@patch("requests.Session")
def test_confluence_search_html_error_fallback_to_content(mock_session_cls, mock_get_client, mock_get_index):
    """Verify that when /search returns an HTML error page (or non-JSON), it falls back to /content?spaceKey=..."""
    mock_chroma_col = MagicMock()
    mock_chroma_col.get.return_value = {"ids": [], "metadatas": []}
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_chroma_col
    mock_get_client.return_value = mock_client

    mock_index = MagicMock()
    mock_get_index.return_value = mock_index

    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__.return_value = mock_session

    # 1. Search endpoint returns HTML error response (e.g. Tomcat / Jersey error page)
    html_error_resp = MagicMock()
    html_error_resp.ok = False
    html_error_resp.status_code = 500
    html_error_resp.reason = "Internal Server Error"
    html_error_resp.text = "<html><body>500 Internal Server Error</body></html>"
    html_error_resp.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")

    # 2. Content endpoint returns valid JSON page list
    content_list_resp = MagicMock()
    content_list_resp.ok = True
    content_list_resp.status_code = 200
    content_list_resp.json.return_value = {
        "results": [
            {
                "id": "501",
                "title": "Fallback Page",
                "space": {"key": "CORE", "name": "Core Space"},
                "version": {"number": 1, "when": "2026-03-15T10:00:00.000Z"},
            }
        ]
    }

    # 3. Phase 2 detail page response
    detail_resp = MagicMock()
    detail_resp.ok = True
    detail_resp.status_code = 200
    detail_resp.json.return_value = {
        "id": "501",
        "title": "Fallback Page",
        "space": {"key": "CORE", "name": "Core Space"},
        "version": {"number": 1, "when": "2026-03-15T10:00:00.000Z"},
        "body": {"storage": {"value": "<p>Content recovered via fallback.</p>"}},
        "_links": {"webui": "/pages/501"},
    }

    def mock_get(url, **kwargs):
        if "501" in url:
            return detail_resp
        elif "/search" in url:
            return html_error_resp
        return content_list_resp

    mock_session.get.side_effect = mock_get

    with patch.object(settings, "confluence_url", "https://wiki.example.com"), \
            patch.object(settings, "confluence_token", "TEST_TOKEN"), \
            patch.object(settings, "confluence_servers", {}):
        ingested, skipped = ingest_confluence(space="CORE")

    assert ingested == 1
    assert skipped == 0
    inserted_docs = mock_index.insert_nodes.call_args[0][0]
    assert len(inserted_docs) == 1
    assert inserted_docs[0].id_ == "confluence-default-501"


@patch("ragdoll.ingest.confluence.get_index")
@patch("ragdoll.ingest.confluence._get_client")
@patch("requests.Session")
def test_confluence_search_unwrapping_content_wrapper(mock_session_cls, mock_get_client, mock_get_index):
    """Verify that search responses wrapping item inside 'content' are correctly normalized."""
    mock_chroma_col = MagicMock()
    mock_chroma_col.get.return_value = {"ids": [], "metadatas": []}
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_chroma_col
    mock_get_client.return_value = mock_client

    mock_index = MagicMock()
    mock_get_index.return_value = mock_index

    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__.return_value = mock_session

    search_resp = MagicMock()
    search_resp.ok = True
    search_resp.status_code = 200
    search_resp.json.return_value = {
        "results": [
            {
                "content": {
                    "id": "601",
                    "title": "CQL Searched Page",
                    "space": {"key": "CORE", "name": "Core Space"},
                    "version": {"number": 1, "when": "2026-03-15T12:00:00.000Z"},
                },
                "title": "CQL Searched Page",
            }
        ]
    }

    detail_resp = MagicMock()
    detail_resp.ok = True
    detail_resp.status_code = 200
    detail_resp.json.return_value = {
        "id": "601",
        "title": "CQL Searched Page",
        "space": {"key": "CORE", "name": "Core Space"},
        "version": {"number": 1, "when": "2026-03-15T12:00:00.000Z"},
        "body": {"storage": {"value": "<p>CQL page content.</p>"}},
        "_links": {"webui": "/pages/601"},
    }

    def mock_get(url, **kwargs):
        if "601" in url:
            return detail_resp
        return search_resp

    mock_session.get.side_effect = mock_get

    with patch.object(settings, "confluence_url", "https://wiki.example.com"), \
            patch.object(settings, "confluence_token", "TEST_TOKEN"), \
            patch.object(settings, "confluence_servers", {}):
        ingested, skipped = ingest_confluence(space="CORE", cql="label = 'release'")

    assert ingested == 1
    inserted_docs = mock_index.insert_nodes.call_args[0][0]
    assert len(inserted_docs) == 1
    assert inserted_docs[0].id_ == "confluence-default-601"


@patch("ragdoll.ingest.confluence.get_index")
@patch("ragdoll.ingest.confluence._get_client")
@patch("requests.Session")
def test_confluence_basic_auth(mock_session_cls, mock_get_client, mock_get_index):
    """Verify that when auth_method='basic' is configured, HTTP Basic Auth is applied directly."""
    mock_chroma_col = MagicMock()
    mock_chroma_col.get.return_value = {"ids": [], "metadatas": []}
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_chroma_col
    mock_get_client.return_value = mock_client

    mock_index = MagicMock()
    mock_get_index.return_value = mock_index

    mock_session = MagicMock()
    mock_session.auth = None
    mock_session.headers = {}
    mock_session.cookies = MagicMock()
    mock_session_cls.return_value.__enter__.return_value = mock_session

    page_resp = MagicMock()
    page_resp.status_code = 200
    page_resp.ok = True
    page_resp.json.return_value = {
        "results": [
            {
                "id": "701",
                "title": "Secured Page",
                "space": {"key": "CORE", "name": "Core Space"},
                "version": {"number": 1, "when": "2026-03-15T12:00:00.000Z"},
            }
        ]
    }

    detail_resp = MagicMock()
    detail_resp.status_code = 200
    detail_resp.ok = True
    detail_resp.json.return_value = {
        "id": "701",
        "title": "Secured Page",
        "space": {"key": "CORE", "name": "Core Space"},
        "version": {"number": 1, "when": "2026-03-15T12:00:00.000Z"},
        "body": {"storage": {"value": "<p>Secured page body.</p>"}},
        "_links": {"webui": "/pages/701"},
    }

    def mock_get(url, **kwargs):
        if "701" in url:
            return detail_resp
        return page_resp

    mock_session.get.side_effect = mock_get

    with patch.object(settings, "confluence_url", "https://wiki.example.com"), \
            patch.object(settings, "confluence_user", "developer"), \
            patch.object(settings, "confluence_token", "TEST_TOKEN"), \
            patch.object(settings, "confluence_auth_method", "basic"), \
            patch.object(settings, "confluence_servers", {}):
        ingested, skipped = ingest_confluence(space="CORE")

    assert ingested == 1
    # Verify session.auth was directly set to Basic auth with user and token
    assert mock_session.auth == ("developer", "TEST_TOKEN")
    inserted_docs = mock_index.insert_nodes.call_args[0][0]
    assert len(inserted_docs) == 1
    assert inserted_docs[0].id_ == "confluence-default-701"


@patch("requests.Session")
def test_confluence_login_page_diagnostic(mock_session_cls):
    """Verify that when a login page redirect occurs, it halts cleanly without probing."""
    mock_session = MagicMock()
    mock_session.auth = None
    mock_session.headers = {}
    mock_session.cookies = MagicMock()
    mock_session_cls.return_value.__enter__.return_value = mock_session

    login_resp = MagicMock()
    login_resp.status_code = 200
    login_resp.ok = True
    login_resp.url = "https://wiki.example.com/login.action"
    login_resp.text = "<html><head><title>Log In - Confluence</title></head><body>Login form</body></html>"
    login_resp.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")

    mock_session.get.return_value = login_resp

    with patch.object(settings, "confluence_url", "https://wiki.example.com"), \
            patch.object(settings, "confluence_user", "developer"), \
            patch.object(settings, "confluence_token", "TEST_TOKEN"), \
            patch.object(settings, "confluence_auth_method", "pat"), \
            patch.object(settings, "confluence_servers", {}):
        ingested, skipped = ingest_confluence(space="CORE")

    assert ingested == 0
    # Crucial: verify mock_session.get was called exactly ONCE (no blind retry probe)
    assert mock_session.get.call_count == 1


@patch("requests.Session")
def test_confluence_waf_challenge_halts_without_retries(mock_session_cls):
    """Verify that Cloudflare / WAF challenges halt immediately without probing or auth retries."""
    mock_session = MagicMock()
    mock_session.auth = None
    mock_session.headers = {}
    mock_session.cookies = MagicMock()
    mock_session_cls.return_value.__enter__.return_value = mock_session

    waf_resp = MagicMock()
    waf_resp.status_code = 200
    waf_resp.ok = True
    waf_resp.url = "https://wiki.example.com/challenge?destination=%2Frest%2Fapi%2Fcontent"
    waf_resp.text = "<html><head><title>Verifying connection</title></head><body>Cloudflare challenge</body></html>"
    waf_resp.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")

    mock_session.get.return_value = waf_resp

    with patch.object(settings, "confluence_url", "https://wiki.example.com"), \
         patch.object(settings, "confluence_user", "developer"), \
         patch.object(settings, "confluence_token", "TEST_TOKEN"), \
         patch.object(settings, "confluence_auth_method", "pat"), \
         patch.object(settings, "confluence_servers", {}):
        ingested, skipped = ingest_confluence(space="CORE")

    assert ingested == 0
    # Crucial: verify that mock_session.get was called exactly ONCE (no auth retries or endpoint probing)
    assert mock_session.get.call_count == 1
    # Verify auth was never altered to Basic auth
    assert mock_session.auth is None


@patch("requests.Session")
def test_confluence_cookie_configuration(mock_session_cls):
    """Verify that custom cookie configuration is applied to the request headers."""
    mock_session = MagicMock()
    mock_session.headers = {}
    mock_session.cookies = MagicMock()
    mock_session_cls.return_value.__enter__.return_value = mock_session

    empty_resp = MagicMock()
    empty_resp.status_code = 200
    empty_resp.ok = True
    empty_resp.json.return_value = {"results": []}
    mock_session.get.return_value = empty_resp

    with patch.object(settings, "confluence_url", "https://wiki.example.com"), \
         patch.object(settings, "confluence_token", "TEST_TOKEN"), \
         patch.object(settings, "confluence_cookie", "cf_clearance=test123cookie; session=xyz"), \
         patch.object(settings, "confluence_servers", {}):
        ingest_confluence(space="CORE")

    # Verify session.headers was updated with Cookie and browser User-Agent
    assert mock_session.headers.get("Cookie") == "cf_clearance=test123cookie; session=xyz"
    assert "Mozilla" in mock_session.headers.get("User-Agent", "")



