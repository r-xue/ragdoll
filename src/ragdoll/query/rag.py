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
    
    if not user_query:
        # Just normal chat without RAG
        for msg in messages:
            role = MessageRole(msg["role"])
            llama_messages.append(ChatMessage(role=role, content=msg["content"]))
    else:
        # Retrieve context.
        results = search(user_query, top_k=top_k, source_filter=source_filter)
        context = _format_context(results) if results else "(No relevant context found.)"

        # Build augmented message list with context as system prompt.
        system_content = f"{SYSTEM_PROMPT}\n\n--- RETRIEVED CONTEXT ---\n{context}\n--- END CONTEXT ---"
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
