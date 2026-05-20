"""Ollama HTTP client for Ragdoll CLI status.

(Note: Generation and Embeddings are now handled natively by LlamaIndex.)
"""

import httpx
from ragdoll.config import settings

def list_models() -> list[str]:
    """Return a list of all model names available on the local Ollama instance."""
    try:
        response = httpx.get(f"{settings.ollama_host}/api/tags", timeout=2.0)
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", [])]
    except Exception:
        return []
