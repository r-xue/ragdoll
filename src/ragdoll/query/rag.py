"""RAG chain — retrieve context, build prompt, call LLM.

This module ties together retrieval and generation into a single
question-answering pipeline.
"""

from __future__ import annotations

import logging
from typing import Generator

from ragdoll.llm import ollama
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
        # (e.g., who is assigned to this Jira ticket, even if this chunk is just a comment)
        meta_items = []
        for k, v in r.metadata.items():
            if k not in ("source", "doc_id", "filepath", "node_type", "key") and v:
                meta_items.append(f"{k.capitalize()}: {v}")
                
        meta_str = " | ".join(meta_items)
        if meta_str:
            parts.append(f"[{source}]\n{meta_str}\n{r.text}")
        else:
            parts.append(f"[{source}]\n{r.text}")
            
    return "\n\n".join(parts)


def ask(
    question: str,
    top_k: int | None = None,
    source_filter: str | None = None,
    stream: bool = False,
) -> str | Generator[str, None, None]:
    """Ask a question using the RAG pipeline.

    Parameters
    ----------
    question : str
        The user's question.
    top_k : int, optional
        Number of context chunks to retrieve.
    source_filter : str, optional
        Limit retrieval to a source type.
    stream : bool
        If True, returns a token generator.

    Returns
    -------
    str or Generator[str, None, None]
    """
    results = search(question, top_k=top_k, source_filter=source_filter)

    if not results:
        msg = "No relevant documents found. Try ingesting some data first."
        if stream:
            def _empty():
                yield msg
            return _empty()
        return msg

    context = _format_context(results)
    prompt = RAG_PROMPT_TEMPLATE.format(context=context, question=question)

    logger.debug("RAG prompt length: %d chars, %d context chunks", len(prompt), len(results))

    return ollama.generate(
        prompt=prompt,
        system=SYSTEM_PROMPT,
        stream=stream,
    )


def summarize(
    topic: str,
    top_k: int | None = None,
    source_filter: str | None = None,
    stream: bool = False,
) -> str | Generator[str, None, None]:
    """Summarize retrieved information about a topic.

    Parameters
    ----------
    topic : str
        The topic to summarize.
    top_k : int, optional
        Number of context chunks.
    source_filter : str, optional
        Limit to a source type.
    stream : bool
        If True, returns a token generator.

    Returns
    -------
    str or Generator[str, None, None]
    """
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

    return ollama.generate(
        prompt=prompt,
        system=SYSTEM_PROMPT,
        stream=stream,
    )


def chat_with_context(
    messages: list[dict[str, str]],
    top_k: int | None = None,
    source_filter: str | None = None,
    stream: bool = False,
) -> str | Generator[str, None, None]:
    """Chat with RAG context injected from the latest user message.

    The most recent user message is used as the retrieval query.
    Retrieved context is prepended to the conversation as a system message.

    Parameters
    ----------
    messages : list[dict]
        Conversation history (``role`` / ``content`` dicts).
    top_k : int, optional
        Number of context chunks.
    source_filter : str, optional
        Limit to a source type.
    stream : bool
        If True, returns a token generator.

    Returns
    -------
    str or Generator[str, None, None]
    """
    # Find the latest user message for retrieval.
    user_query = ""
    for msg in reversed(messages):
        if msg["role"] == "user":
            user_query = msg["content"]
            break

    if not user_query:
        return ollama.chat(messages, stream=stream)

    # Retrieve context.
    results = search(user_query, top_k=top_k, source_filter=source_filter)
    context = _format_context(results) if results else "(No relevant context found.)"

    # Build augmented message list with context as system prompt.
    augmented = [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\n\n--- RETRIEVED CONTEXT ---\n{context}\n--- END CONTEXT ---"},
    ]
    # Add conversation history (skip any existing system messages).
    for msg in messages:
        if msg["role"] != "system":
            augmented.append(msg)

    return ollama.chat(augmented, stream=stream)
