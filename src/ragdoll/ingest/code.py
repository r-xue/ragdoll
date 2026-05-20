"""Python source-code ingestion.

Walks a directory tree for ``*.py`` files and uses the ``ast`` module to
extract semantically meaningful units — functions, classes, and
module-level docstrings — as separate Documents for the RAG pipeline.

This gives the LLM coherent, self-contained code blocks to reason about
rather than randomly split text fragments.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from textwrap import dedent

from llama_index.core import Document
from ragdoll.store.vectordb import get_index

logger = logging.getLogger(__name__)

# File patterns to ignore when walking directories.
_IGNORE_DIRS = {
    "__pycache__",
    ".git",
    ".pixi",
    ".tox",
    ".venv",
    "venv",
    "node_modules",
    ".eggs",
    "*.egg-info",
}


def _read_file(path: Path) -> str | None:
    """Read a Python file, returning None on decode errors."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Cannot read %s: %s", path, exc)
        return None


def _extract_nodes(source: str, filepath: str) -> list[Document]:
    """Parse a Python source file and extract top-level code units.

    Extracts:
    - Module docstring (if present)
    - Top-level functions (``def``)
    - Top-level classes (``class``) including all their methods
    - Standalone top-level code (assignments, constants, etc.)

    Each extracted unit becomes a separate Document with metadata about
    the file path, node type, name, and line range.
    """
    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError as exc:
        logger.warning("Syntax error in %s: %s — falling back to raw text.", filepath, exc)
        return [
            Document(
                doc_id=f"code:{filepath}",
                text=source,
                metadata={
                    "source": "code",
                    "filepath": filepath,
                    "node_type": "raw",
                    "name": Path(filepath).name,
                },
            )
        ]

    lines = source.splitlines(keepends=True)
    documents: list[Document] = []

    # Module docstring.
    module_doc = ast.get_docstring(tree)
    if module_doc:
        documents.append(
            Document(
                doc_id=f"code:{filepath}::module_doc",
                text=f"# Module: {filepath}\n\n{module_doc}",
                metadata={
                    "source": "code",
                    "filepath": filepath,
                    "node_type": "module_doc",
                    "name": Path(filepath).stem,
                },
            )
        )

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _extract_function(node, lines, filepath, documents)
        elif isinstance(node, ast.ClassDef):
            _extract_class(node, lines, filepath, documents)

    return documents


def _get_source_segment(
    lines: list[str], node: ast.AST
) -> str:
    """Extract the source lines for an AST node."""
    start = node.lineno - 1  # 0-indexed
    end = getattr(node, "end_lineno", None)
    if end is None:
        # Fallback: grab until next node or EOF.
        end = len(lines)
    segment = "".join(lines[start:end])
    return dedent(segment)


def _extract_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    lines: list[str],
    filepath: str,
    documents: list[Document],
) -> None:
    """Extract a top-level function as a Document."""
    source = _get_source_segment(lines, node)
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    header = f"# {filepath} — {prefix}def {node.name}()\n\n"

    documents.append(
        Document(
            doc_id=f"code:{filepath}::{node.name}",
            text=header + source,
            metadata={
                "source": "code",
                "filepath": filepath,
                "node_type": "function",
                "name": node.name,
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", None),
            },
        )
    )


def _extract_class(
    node: ast.ClassDef,
    lines: list[str],
    filepath: str,
    documents: list[Document],
) -> None:
    """Extract a class as a Document.

    The entire class body (including methods) is treated as one unit so
    the LLM sees the full class context.
    """
    source = _get_source_segment(lines, node)
    header = f"# {filepath} — class {node.name}\n\n"

    documents.append(
        Document(
            doc_id=f"code:{filepath}::{node.name}",
            text=header + source,
            metadata={
                "source": "code",
                "filepath": filepath,
                "node_type": "class",
                "name": node.name,
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", None),
            },
        )
    )


def _should_skip_dir(dirname: str) -> bool:
    """Return True if a directory should be skipped."""
    return dirname in _IGNORE_DIRS or dirname.endswith(".egg-info")


def ingest_code(paths: list[Path]) -> list[Document]:
    """Ingest Python source files from files and/or directories.

    Args:
        paths (list[Path]): Files or directories to ingest. Directories are walked
            recursively for ``*.py`` files.

    Returns:
        list[Document]: One or more Documents per Python file (one per function/class).
    """
    py_files: list[Path] = []

    for p in paths:
        if p.is_file() and p.suffix == ".py":
            py_files.append(p)
        elif p.is_dir():
            for child in sorted(p.rglob("*.py")):
                # Skip ignored directories.
                if any(_should_skip_dir(part) for part in child.parts):
                    continue
                py_files.append(child)
        else:
            logger.warning("Skipping non-Python path: %s", p)

    logger.info("Found %d Python file(s) to ingest.", len(py_files))

    all_docs: list[Document] = []
    for pyfile in py_files:
        source = _read_file(pyfile)
        if source is None:
            continue

        filepath = str(pyfile)
        docs = _extract_nodes(source, filepath)
        all_docs.extend(docs)
        logger.debug("Extracted %d nodes from %s", len(docs), filepath)

    logger.info("Extracted %d code documents from %d files.", len(all_docs), len(py_files))
    return all_docs
