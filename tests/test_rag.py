"""Tests for RAG query routing, JQL generation, and hybrid retrieval."""

import pytest
from unittest.mock import MagicMock, patch
from ragdoll.query.rag import chat_with_context, query_live_jira, JQL_GENERATOR_PROMPT


def test_jql_prompt_rules():
    """Verify JQL generator prompt contains high-recall rules."""
    assert "text ~" in JQL_GENERATOR_PROMPT
    assert "labels" in JQL_GENERATOR_PROMPT
    assert "statusCategory != Done" in JQL_GENERATOR_PROMPT
    assert "Multi-Concept Separation" in JQL_GENERATOR_PROMPT
    assert "Avoid Auxiliary & Structural Term Overfitting" in JQL_GENERATOR_PROMPT


def test_query_live_jira_formatting():
    """Verify query_live_jira formats components, labels, and description snippet."""
    mock_issue = MagicMock()
    mock_issue.key = "PROJ-1234"
    mock_issue.fields.summary = "Too long parameter name is truncated in the dashboard"
    mock_issue.fields.status.name = "Open"
    mock_issue.fields.issuetype.name = "Bug"
    mock_issue.fields.priority.name = "Minor"
    mock_issue.fields.assignee.displayName = "Unassigned"
    mock_issue.fields.updated = "2024-03-01"
    mock_issue.fields.labels = ["dashboard", "report"]

    mock_comp = MagicMock()
    mock_comp.name = "dashboard"
    mock_issue.fields.components = [mock_comp]
    mock_issue.fields.description = "In the 'Input Parameters' section in the task summary page, parameter names are truncated."

    mock_reader = MagicMock()
    mock_issues = MagicMock()
    mock_issues.__iter__.return_value = [mock_issue]
    mock_issues.__len__.return_value = 1
    mock_issues.total = 1
    mock_reader.jira.search_issues.return_value = mock_issues

    with patch("llama_index.readers.jira.JiraReader", return_value=mock_reader), \
         patch("ragdoll.config.settings.jira_url", "https://jira.internal"), \
         patch("ragdoll.config.settings.jira_token", "fake-token"):
        
        result_str = query_live_jira('project = PROJ')
        assert "PROJ-1234" in result_str
        assert "Components: dashboard" in result_str
        assert "Labels: dashboard, report" in result_str
        assert "Description: In the 'Input Parameters' section in the task summary page" in result_str


def test_jira_hybrid_retrieval():
    """Verify JIRA_DATABASE intent enriches live results with semantic ChromaDB search."""
    mock_fast_llm = MagicMock()
    mock_active_llm = MagicMock()

    # Mock intent classification as JIRA_DATABASE
    intent_resp = MagicMock()
    intent_resp.message.content = "JIRA_DATABASE"

    # Mock JQL generation
    jql_resp = MagicMock()
    jql_resp.message.content = 'statusCategory != Done AND (text ~ "dashboard" OR labels = "dashboard")'

    mock_fast_llm.chat.side_effect = [intent_resp, jql_resp]

    # Mock final LLM streaming/chat response
    final_resp = MagicMock()
    final_resp.message.content = "Here are the tickets about dashboard..."
    mock_active_llm.chat.return_value = final_resp

    # Mock query_live_jira returning 1 live ticket (PROJ-100)
    live_jira_text = "### Results from primary:\n- PROJ-100 [Bug] (Open): Fix dashboard parameter display"

    # Mock search() returning 2 semantic tickets: PROJ-100 (already live) and PROJ-200 (semantic discovery)
    from ragdoll.query.retriever import SearchResult
    sem_r1 = SearchResult(chunk_id="c1", text="PROJ-100 details", score=0.9, metadata={"key": "PROJ-100", "source": "jira"})
    sem_r2 = SearchResult(chunk_id="c2", text="PROJ-200: Dashboard task inputs validation", score=0.85, metadata={"key": "PROJ-200", "source": "jira"})

    def get_llm_mock(thinking=None):
        if thinking is False:
            return mock_fast_llm
        return mock_active_llm

    with patch("ragdoll.query.rag.get_llm", side_effect=get_llm_mock), \
         patch("ragdoll.query.rag.query_live_jira", return_value=live_jira_text), \
         patch("ragdoll.query.rag.search", return_value=[sem_r1, sem_r2]) as mock_search:

        messages = [{"role": "user", "content": "list active tickets about dashboard inputs"}]
        answer = chat_with_context(messages, stream=False)

        assert answer == "Here are the tickets about dashboard..."

        # Verify semantic vector search was queried
        mock_search.assert_called_once()
        _, kwargs = mock_search.call_args
        assert kwargs.get("source_filter") == "jira"

        # Verify the augmented system prompt sent to active LLM contains both live and vector results
        sent_messages = mock_active_llm.chat.call_args[0][0]
        system_msg = sent_messages[0].content
        assert "--- LIVE DATABASE RESULTS ---" in system_msg
        assert "PROJ-100" in system_msg
        assert "--- ADDITIONAL RELEVANT TICKETS (FROM INDEXED VECTOR DB) ---" in system_msg
        assert "PROJ-200" in system_msg
        assert "Never output <think> or </think> tags" in system_msg


def test_sanitize_response():
    """Verify _sanitize_response strips thinking blocks and orphaned tags."""
    from ragdoll.query.rag import _sanitize_response

    # Empty string
    assert _sanitize_response("") == ""

    # Clean text
    clean = "This is a clean response with verbatim citations [jira-PROJ-123]."
    assert _sanitize_response(clean) == clean

    # Orphaned pre-think scratchpad with </think>
    orphaned = (
        "Drafting internal thoughts about the query...\n"
        "[Note: Context doesn't specify data column.]\n"
        "</think>\n"
        "This is the actual final response [jira-PROJ-123]."
    )
    assert _sanitize_response(orphaned) == "This is the actual final response [jira-PROJ-123]."

    # Fully enclosed <think>...</think> block
    enclosed = (
        "<think>\nInternal reasoning here\n</think>\n\n"
        "Final structured answer."
    )
    assert _sanitize_response(enclosed) == "Final structured answer."


def test_clean_stream():
    """Verify _clean_stream strips opening thinking blocks and stray tags."""
    from ragdoll.query.rag import _clean_stream

    class Chunk:
        def __init__(self, delta: str):
            self.delta = delta

    # 1. Normal clean stream
    chunks1 = [Chunk("Based "), Chunk("on "), Chunk("data.")]
    assert "".join(_clean_stream(chunks1)) == "Based on data."

    # 2. Stream starting with <think>...</think>
    chunks2 = [
        Chunk("<think>\n"),
        Chunk("reasoning "),
        Chunk("step 1\n"),
        Chunk("</think>\n"),
        Chunk("Final answer."),
    ]
    assert "".join(_clean_stream(chunks2)).strip() == "Final answer."

    # 3. Stream with stray </think> tag
    chunks3 = [Chunk("Pre "), Chunk("</think>"), Chunk("Post")]
    assert "".join(_clean_stream(chunks3)) == "Pre Post"
