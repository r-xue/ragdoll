"""RAG chain via LlamaIndex.

This module ties together retrieval and generation into a single
question-answering pipeline using LlamaIndex LLM engines.
"""

from __future__ import annotations

import logging
from typing import Generator
import re

from llama_index.core import Settings
from llama_index.core.base.llms.types import ChatMessage, MessageRole
from ragdoll.query.retriever import SearchResult, search

logger = logging.getLogger(__name__)

# ── Prompt templates ───────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are Ragdoll, an expert assistant for engineering knowledge.
You answer questions based ONLY on the provided context from JIRA tickets \
and internal documentation.
If the context doesn't contain enough information, say so honestly.
Always cite the source document IDs when referencing specific information.
Be concise but thorough."""

RAG_PROMPT_TEMPLATE = """\
Use the following context to answer the question.
Each piece of context has a source ID in square brackets.

--- CONTEXT ---
{context}
--- END CONTEXT ---

Question: {question}

Answer (cite sources using [source_id]):"""

SUMMARIZE_PROMPT_TEMPLATE = """\
Summarize the following information retrieved from internal JIRA tickets \
and documentation. Be concise but capture all key points.
Cite source IDs in [brackets].

--- CONTEXT ---
{context}
--- END CONTEXT ---

Topic: {topic}

Summary:"""


INTENT_PROMPT = """\
Determine if the user's question requires searching a LIVE DATABASE for a list/aggregation of tickets (e.g. "list all bugs", "how many tickets"), or if it requires reading technical documentation to answer a KNOWLEDGE question (e.g. "how do I fix X", "what is Y").
Reply ONLY with the exact word "DATABASE" or "KNOWLEDGE".

Question: {question}
Intent:"""

JQL_GENERATOR_PROMPT = """\
You are an expert Atlassian JIRA administrator.
Convert the user's natural language request into a valid JQL (Jira Query Language) string.
Return ONLY the raw JQL string, nothing else. No markdown formatting, no explanations.

User Request: {question}
JQL:"""


def _format_context(results: list[SearchResult]) -> str:
    """Format search results into a context block for the LLM."""
    parts: list[str] = []
    for r in results:
        source = r.metadata.get("doc_id", r.chunk_id)
        
        # Build a metadata header for the chunk to preserve context
        meta_str = ", ".join(f"{k}: {v}" for k, v in r.metadata.items() if k != "doc_id")
        
        parts.append(f"[{source}] (Meta: {meta_str})\n{r.text.strip()}")
    return "\n\n".join(parts)


def query(
    question: str,
    top_k: int | None = None,
    source_filter: str | None = None,
    stream: bool = False,
) -> str | Generator[str, None, None]:
    """Single-turn RAG query."""
    results = search(question, top_k=top_k, source_filter=source_filter)
    context = _format_context(results) if results else "(No relevant context found.)"
    prompt = RAG_PROMPT_TEMPLATE.format(context=context, question=question)

    messages = [
        ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
        ChatMessage(role=MessageRole.USER, content=prompt),
    ]
    
    if stream:
        resp = Settings.llm.stream_chat(messages)
        return (chunk.delta for chunk in resp)
    
    resp = Settings.llm.chat(messages)
    return resp.message.content or ""


def summarize(
    topic: str,
    top_k: int | None = None,
    source_filter: str | None = None,
    stream: bool = False,
) -> str | Generator[str, None, None]:
    """Summarize context retrieved for a topic."""
    results = search(topic, top_k=top_k, source_filter=source_filter)

    if not results:
        msg = "No relevant documents found for this topic."
        if stream:
            def _empty():
                yield msg
            return _empty()
        return msg

    context = _format_context(results)
    prompt = SUMMARIZE_PROMPT_TEMPLATE.format(context=context, topic=topic)

    messages = [
        ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
        ChatMessage(role=MessageRole.USER, content=prompt),
    ]

    if stream:
        resp = Settings.llm.stream_chat(messages)
        return (chunk.delta for chunk in resp)
        
    resp = Settings.llm.chat(messages)
    return resp.message.content or ""


def query_live_jira(jql: str) -> str:
    """Execute a JQL query directly against all configured JIRA APIs."""
    from llama_index.readers.jira import JiraReader
    from ragdoll.config import settings
    
    # Collect all server configs to query
    configs_to_query = []
    
    # Always include the top-level (global) default server if it's explicitly configured
    if settings.jira_url and settings.jira_url != "https://jira.example.com" and settings.jira_token:
        configs_to_query.append({
            "name": "default",
            "url": settings.jira_url,
            "user": settings.jira_user,
            "token": settings.jira_token,
            "auth_method": settings.jira_auth_method,
        })
        
    if settings.jira_servers:
        for name, cfg in settings.jira_servers.items():
            url = cfg.get("url", settings.jira_url)
            
            # Skip unconfigured dummy URLs
            if url == "https://jira.example.com":
                continue
                
            # Avoid adding the exact same server twice if the user duplicated it
            if any(c["url"] == url for c in configs_to_query):
                continue
                
            configs_to_query.append({
                "name": name,
                "url": url,
                "user": cfg.get("user", settings.jira_user),
                "token": cfg.get("token", settings.jira_token),
                "auth_method": cfg.get("auth_method", settings.jira_auth_method),
            })

    all_results = []
    for cfg in configs_to_query:
        server_url = cfg["url"]
        if server_url.startswith("https://"):
            server_url = server_url[8:]
        elif server_url.startswith("http://"):
            server_url = server_url[7:]
            
        try:
            if cfg["auth_method"] == "pat":
                reader = JiraReader(
                    PATauth={
                        "server_url": cfg["url"],
                        "api_token": cfg["token"],
                    }
                )
            else:
                reader = JiraReader(
                    email=cfg["user"],
                    api_token=cfg["token"],
                    server_url=server_url,
                )
            jira_client = reader.jira
            issues = jira_client.search_issues(jql, maxResults=50)
            
            if issues:
                all_results.append(f"### Results from {cfg['name']} ({server_url}):\nFound {issues.total} total tickets. Showing top {len(issues)}:")
                for issue in issues:
                    key = issue.key
                    summary = issue.fields.summary
                    status = issue.fields.status.name if issue.fields.status else "Unknown"
                    assignee = issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned"
                    updated = issue.fields.updated
                    all_results.append(f"- {key} ({status}): {summary} | Assignee: {assignee} | Updated: {updated}")
        except Exception as e:
            all_results.append(f"### Results from {cfg['name']} ({server_url}):\nFailed to execute JQL '{jql}': {str(e)}")

    if not all_results:
        return "No tickets found matching this JQL across any configured Jira servers."
        
    return "\n".join(all_results)


def chat_with_context(
    messages: list[dict[str, str]],
    top_k: int | None = None,
    source_filter: str | None = None,
    stream: bool = False,
) -> str | Generator[str, None, None]:
    """Chat with RAG context injected from the latest user message."""
    user_query = ""
    for msg in reversed(messages):
        if msg["role"] == "user":
            user_query = msg["content"]
            # Clean up Open WebUI's injected chat history
            user_query = re.sub(r'<chat_history>.*?</chat_history>', '', user_query, flags=re.DOTALL).strip()
            break

    llama_messages = []
    
    if not user_query or user_query.startswith("### Task:\n"):
        # Just normal chat without RAG (or fast-path for Open WebUI background tasks)
        for msg in messages:
            role = MessageRole(msg["role"])
            llama_messages.append(ChatMessage(role=role, content=msg["content"]))
    else:
        # Route query: Database vs Knowledge
        try:
            intent_msg = Settings.llm.chat([ChatMessage(role=MessageRole.USER, content=INTENT_PROMPT.format(question=user_query))])
            intent = intent_msg.message.content.strip().upper()
            logger.info("Query Intent Classified as: %s", intent)
        except Exception as e:
            logger.warning("Intent classification failed: %s", e)
            intent = "KNOWLEDGE"
            
        if "DATABASE" in intent:
            logger.info("Routing query to Live JIRA Database...")
            try:
                jql_msg = Settings.llm.chat([ChatMessage(role=MessageRole.USER, content=JQL_GENERATOR_PROMPT.format(question=user_query))])
                jql = jql_msg.message.content.strip()
                jql = re.sub(r"^```jql\s*|```\s*$", "", jql, flags=re.IGNORECASE).strip()
                logger.info("Generated JQL: %s", jql)
                
                live_results = query_live_jira(jql)
                system_content = f"{SYSTEM_PROMPT}\n\n--- LIVE DATABASE RESULTS ---\n{live_results}\n--- END RESULTS ---"
            except Exception as e:
                logger.error("JQL Generation failed: %s", e)
                system_content = f"{SYSTEM_PROMPT}\n\n(Failed to query live database.)"
                
        else:
            # Retrieve context.
            results = search(user_query, top_k=top_k, source_filter=source_filter)
            context = _format_context(results) if results else "(No relevant context found.)"
            system_content = f"{SYSTEM_PROMPT}\n\n--- RETRIEVED CONTEXT ---\n{context}\n--- END CONTEXT ---"

        # Build augmented message list with context as system prompt.
        llama_messages.append(ChatMessage(role=MessageRole.SYSTEM, content=system_content))
        
        # Add conversation history
        for msg in messages:
            if msg["role"] != "system":
                role = MessageRole(msg["role"])
                llama_messages.append(ChatMessage(role=role, content=msg["content"]))

    if stream:
        resp = Settings.llm.stream_chat(llama_messages)
        return (chunk.delta or "" for chunk in resp)
        
    resp = Settings.llm.chat(llama_messages)
    return resp.message.content or ""
