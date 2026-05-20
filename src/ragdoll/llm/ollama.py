"""Ollama LLM client.

Provides embedding and text generation via the Ollama HTTP API.
All calls are synchronous (using httpx) for simplicity.
"""

from __future__ import annotations

import json
import logging
from typing import Generator

import httpx

from ragdoll.config import settings

logger = logging.getLogger(__name__)

# Long timeout for LLM generation on consumer GPUs.
_TIMEOUT = httpx.Timeout(timeout=300.0, connect=10.0)


def embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Compute embeddings for a batch of texts.

    Parameters
    ----------
    texts : list[str]
        Texts to embed.
    model : str, optional
        Ollama model name (default: from settings).

    Returns
    -------
    list[list[float]]
        One embedding vector per input text.
    """
    model = model or settings.embed_model
    url = f"{settings.ollama_host}/api/embed"

    # Sanitise inputs: Ollama rejects empty strings, and
    # nomic-embed-text has a 2048-token context window.
    # Technical text tokenizes at ~2–3 chars/token, so cap at 2000 chars.
    _MAX_EMBED_CHARS = 2000

    cleaned = []
    for t in texts:
        t = t.strip() if t else ""
        if not t:
            t = "(empty)"  # placeholder so indices stay aligned
        if len(t) > _MAX_EMBED_CHARS:
            logger.debug("Truncating text from %d to %d chars for embedding.", len(t), _MAX_EMBED_CHARS)
            t = t[:_MAX_EMBED_CHARS]
        cleaned.append(t)

    resp = httpx.post(
        url,
        json={"model": model, "input": cleaned},
        timeout=_TIMEOUT,
    )

    if resp.status_code != 200:
        # Log the actual error body so we can diagnose what Ollama rejected.
        logger.error(
            "Ollama embed error %d: %s (batch size=%d, max text len=%d)",
            resp.status_code,
            resp.text[:500],
            len(cleaned),
            max(len(t) for t in cleaned),
        )
        resp.raise_for_status()

    data = resp.json()
    embeddings = data["embeddings"]
    logger.debug("Embedded %d texts with %s (dim=%d)", len(texts), model, len(embeddings[0]))
    return embeddings


def generate(
    prompt: str,
    model: str | None = None,
    system: str | None = None,
    temperature: float | None = None,
    stream: bool = False,
) -> str | Generator[str, None, None]:
    """Generate a completion from a prompt.

    Parameters
    ----------
    prompt : str
        The user prompt.
    model : str, optional
        Ollama model name (default: from settings).
    system : str, optional
        System prompt.
    temperature : float, optional
        Sampling temperature.
    stream : bool
        If True, returns a generator that yields token strings.

    Returns
    -------
    str or Generator[str, None, None]
        The full response text, or a streaming generator.
    """
    model = model or settings.chat_model
    temperature = temperature if temperature is not None else settings.temperature
    url = f"{settings.ollama_host}/api/generate"

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": stream,
        "options": {"temperature": temperature},
    }
    if system:
        payload["system"] = system

    if stream:
        return _stream_generate(url, payload)

    resp = httpx.post(url, json=payload, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["response"]


def _stream_generate(url: str, payload: dict) -> Generator[str, None, None]:
    """Internal: stream tokens from Ollama generate endpoint."""
    with httpx.stream("POST", url, json=payload, timeout=_TIMEOUT) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line:
                data = json.loads(line)
                token = data.get("response", "")
                if token:
                    yield token
                if data.get("done"):
                    return


def chat(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float | None = None,
    stream: bool = False,
) -> str | Generator[str, None, None]:
    """Send a multi-turn chat conversation to Ollama.

    Parameters
    ----------
    messages : list[dict]
        List of ``{"role": "system"|"user"|"assistant", "content": "..."}``
        messages.
    model : str, optional
        Ollama model name.
    temperature : float, optional
        Sampling temperature.
    stream : bool
        If True, returns a token generator.

    Returns
    -------
    str or Generator[str, None, None]
    """
    model = model or settings.chat_model
    temperature = temperature if temperature is not None else settings.temperature
    url = f"{settings.ollama_host}/api/chat"

    payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "options": {"temperature": temperature},
    }

    if stream:
        return _stream_chat(url, payload)

    resp = httpx.post(url, json=payload, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def _stream_chat(url: str, payload: dict) -> Generator[str, None, None]:
    """Internal: stream tokens from Ollama chat endpoint."""
    with httpx.stream("POST", url, json=payload, timeout=_TIMEOUT) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line:
                data = json.loads(line)
                token = data.get("message", {}).get("content", "")
                if token:
                    yield token
                if data.get("done"):
                    return


def list_models() -> list[dict]:
    """List models available in the local Ollama instance."""
    url = f"{settings.ollama_host}/api/tags"
    resp = httpx.get(url, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("models", [])
