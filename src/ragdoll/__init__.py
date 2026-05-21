"""Ragdoll — Retrieval-Augmented Generation Driven by Offline Local LLMs.

A fully-local RAG system for JIRA tickets and PDF documents, powered by Ollama.
"""

import warnings
# Suppress noisy Pydantic warnings originating from LlamaIndex dependencies at import time
warnings.filterwarnings("ignore", message=".*validate_default.*")

__version__ = "0.1.0"
