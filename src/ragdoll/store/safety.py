"""Utilities for preventing and detecting ChromaDB corruption.

ChromaDB's Rust HNSW backend writes to binary index files during
``index.insert()``.  If ``^C`` (SIGINT) arrives mid-write, those files
can become inconsistent, causing a native segfault on subsequent reads.

This module provides:

- **GracefulInterrupt**: A context manager that defers ``^C`` during
  critical write sections so the current insert can finish cleanly.
- **check_chromadb_health**: A lightweight probe that detects a corrupted
  database and prints actionable recovery instructions.
"""

from __future__ import annotations

import logging
import signal
from typing import Any

from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()


class GracefulInterrupt:
    """Defer SIGINT during critical ChromaDB writes to prevent corruption.

    Usage::

        with GracefulInterrupt() as gi:
            for doc in documents:
                index.insert(doc)
                if gi.interrupted:
                    break  # exit cleanly between inserts

    On ``^C`` the handler prints a warning and sets ``self.interrupted``.
    When the context exits, the original handler is restored and
    ``KeyboardInterrupt`` is re-raised if the flag was set.
    """

    def __init__(self) -> None:
        self.interrupted = False
        self._original_handler: Any = None

    def _handler(self, signum: int, frame: Any) -> None:
        self.interrupted = True
        console.print(
            "\n[yellow]⚠ Interrupt received — finishing current write to prevent "
            "database corruption. Please wait…[/yellow]"
        )

    def __enter__(self) -> GracefulInterrupt:
        self._original_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._handler)
        return self

    def __exit__(self, *args: Any) -> None:
        signal.signal(signal.SIGINT, self._original_handler or signal.SIG_DFL)
        if self.interrupted:
            console.print(
                "[yellow]⚠ Write completed safely. Aborting as requested.[/yellow]"
            )
            raise KeyboardInterrupt


def check_chromadb_health() -> bool:
    """Quick canary check on the local ChromaDB collection.

    Attempts a lightweight ``count()`` inside an isolated subprocess with a 10s
    timeout so that a segfault or hang in the Rust backend does not kill the main process.

    Returns:
        True if the database is healthy, False if corrupted.
    """
    import os
    import subprocess
    import sys
    from ragdoll.config import settings

    # If remote ChromaDB is configured, skip local file-level health check
    if settings.chroma_host:
        return True

    # If local chroma directory or sqlite file does not exist yet, it's fresh/clean
    if not settings.chroma_dir.exists() or not (settings.chroma_dir / "chroma.sqlite3").exists():
        return True

    cmd = [
        sys.executable,
        "-c",
        "from ragdoll.store.vectordb import count; count()",
    ]
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10.0,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        logger.warning("ChromaDB health check timed out after 10s (possible SQLite lock contention).")
        return False
    except Exception as e:
        logger.debug("Failed to spawn ChromaDB health check probe: %s", e)
        return True

    # Check for crash return codes (SIGSEGV / SIGBUS / abort)
    sigsegv_val = signal.SIGSEGV.value
    sigbus_val = getattr(signal, "SIGBUS", signal.SIGSEGV).value
    if res.returncode in (-sigsegv_val, -sigbus_val, 128 + sigsegv_val, 128 + sigbus_val):
        console.print(
            "\n[bold red]⚠ ChromaDB database corruption detected![/bold red]\n"
            "[yellow]The vector store index is corrupted (likely from a previous ^C interrupt).\n"
            "Recovery:[/yellow]\n"
            "  1. Run: [bold]ragdoll clear --force[/bold]\n"
            "  2. Re-ingest: [bold]ragdoll ingest all . --clone --force[/bold]\n"
        )
        return False

    return True

