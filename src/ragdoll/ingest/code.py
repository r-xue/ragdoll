"""Multi-language source-code ingestion module.

Recursively walks directories for source code files across multiple languages:
- Python (.py)
- C / C++ (.c, .h, .cpp, .cc, .cxx, .hpp, .hh, .hxx, .tcc, .cu, .cuh)
- Fortran (.f, .for, .f90, .f95)
- Shell Scripts (.sh, .bash, .zsh)
- Templates & Build (CMakeLists.txt, .cmake, .xml, .mako, Makefile, Dockerfile)
- Config & Modern Languages (.json, .yaml, .yml, .toml, .rs, .go, .js, .ts, .sql)

Extracts semantically meaningful code units (classes, functions, subroutines)
or coherent chunk blocks for the RAG vector store.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from textwrap import dedent

from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter

logger = logging.getLogger(__name__)

# File patterns and directories to ignore when walking trees.
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
    "build",
    "dist",
    ".mypy_cache",
    ".pytest_cache",
}

# Binary/artifact file extensions to ignore.
_IGNORE_EXTS = {
    ".o",
    ".so",
    ".a",
    ".dylib",
    ".dll",
    ".exe",
    ".class",
    ".pyc",
    ".pyo",
    ".tar",
    ".gz",
    ".zip",
    ".bin",
    ".dat",
    ".png",
    ".jpg",
    ".jpeg",
    ".pdf",
}

# Supported file extensions mapped to normalized language names.
SUPPORTED_EXTENSIONS: dict[str, str] = {
    # Python
    ".py": "python",
    # C / C++
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".tcc": "cpp",
    ".cu": "cuda",
    ".cuh": "cuda",
    # Fortran
    ".f": "fortran",
    ".for": "fortran",
    ".f90": "fortran",
    ".f95": "fortran",
    # Shell
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    # Templates & Build
    ".xml": "xml",
    ".mako": "mako",
    ".cmake": "cmake",
    # Modern Languages
    ".rs": "rust",
    ".go": "go",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    # Config & Queries
    ".sql": "sql",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    # LaTeX & Scientific Documents
    ".tex": "latex",
    ".latex": "latex",
    ".sty": "latex",
    ".cls": "latex",
    ".bib": "bibtex",
    # Markdown & Documentation
    ".md": "markdown",
    ".markdown": "markdown",
    ".rst": "rst",
    ".txt": "text",
}

SPECIAL_FILENAMES: dict[str, str] = {
    "CMakeLists.txt": "cmake",
    "Makefile": "makefile",
    "Dockerfile": "dockerfile",
}


def _read_file(path: Path) -> str | None:
    """Read a source file, returning None on decode or read errors."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Cannot read %s: %s", path, exc)
        return None


def _should_skip_dir(dirname: str) -> bool:
    """Return True if a directory name should be skipped."""
    return dirname in _IGNORE_DIRS or dirname.endswith(".egg-info")


# ── Python Extraction AST ─────────────────────────────────────

def _extract_python_nodes(source: str, filepath: str) -> list[Document]:
    """Parse a Python source file using standard library AST."""
    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError as exc:
        logger.warning("Syntax error in %s: %s — falling back to raw chunking.", filepath, exc)
        return _extract_generic_nodes(source, filepath, "python")

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
                    "language": "python",
                    "node_type": "module_doc",
                    "name": Path(filepath).stem,
                    "lineno": 1,
                },
            )
        )

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _extract_py_function(node, lines, filepath, documents)
        elif isinstance(node, ast.ClassDef):
            _extract_py_class(node, lines, filepath, documents)

    # Fallback if no functions/classes found (e.g. flat script)
    if not documents and source.strip():
        documents.append(
            Document(
                doc_id=f"code:{filepath}",
                text=f"# File: {filepath} (python)\n\n{source}",
                metadata={
                    "source": "code",
                    "filepath": filepath,
                    "language": "python",
                    "node_type": "raw",
                    "name": Path(filepath).name,
                    "lineno": 1,
                    "end_lineno": len(lines),
                },
            )
        )

    return documents


def _get_py_source_segment(lines: list[str], node: ast.AST) -> str:
    """Extract the source lines for an AST node."""
    start = node.lineno - 1
    end = getattr(node, "end_lineno", None) or len(lines)
    segment = "".join(lines[start:end])
    return dedent(segment)


def _extract_py_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    lines: list[str],
    filepath: str,
    documents: list[Document],
) -> None:
    source = _get_py_source_segment(lines, node)
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    header = f"# {filepath} — {prefix}def {node.name}()\n\n"

    documents.append(
        Document(
            doc_id=f"code:{filepath}::{node.name}:{node.lineno}",
            text=header + source,
            metadata={
                "source": "code",
                "filepath": filepath,
                "language": "python",
                "node_type": "function",
                "name": node.name,
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", None),
            },
        )
    )


def _extract_py_class(
    node: ast.ClassDef,
    lines: list[str],
    filepath: str,
    documents: list[Document],
) -> None:
    source = _get_py_source_segment(lines, node)
    header = f"# {filepath} — class {node.name}\n\n"

    documents.append(
        Document(
            doc_id=f"code:{filepath}::{node.name}:{node.lineno}",
            text=header + source,
            metadata={
                "source": "code",
                "filepath": filepath,
                "language": "python",
                "node_type": "class",
                "name": node.name,
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", None),
            },
        )
    )


# ── C / C++ Semantic Block Extraction ────────────────────────────

def _extract_cpp_nodes(
    source: str, filepath: str, chunk_size: int = 1500, chunk_overlap: int = 200
) -> list[Document]:
    """Extract C/C++ semantic blocks (classes, structs, functions, namespaces)."""
    lines = source.splitlines()
    if not lines:
        return []

    # If the file is small (under 60 lines or 1500 chars), keep it intact
    if len(lines) <= 30 and len(source) <= chunk_size:
        return [
            Document(
                doc_id=f"code:{filepath}",
                text=f"// File: {filepath} (C/C++)\n\n{source}",
                metadata={
                    "source": "code",
                    "filepath": filepath,
                    "language": "cpp",
                    "node_type": "file",
                    "name": Path(filepath).name,
                    "lineno": 1,
                    "end_lineno": len(lines),
                },
            )
        ]

    documents: list[Document] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
            i += 1
            continue

        # Look for class, struct, namespace, or function signatures
        if ("class " in stripped or "struct " in stripped or "(" in stripped) and not stripped.startswith("#"):
            start_line = i
            brace_count = line.count("{") - line.count("}")

            # Check if block opens on current or following line
            if "{" in line or (i + 1 < len(lines) and "{" in lines[i + 1]):
                while i + 1 < len(lines) and brace_count == 0:
                    i += 1
                    brace_count += lines[i].count("{") - lines[i].count("}")

                while i + 1 < len(lines) and brace_count > 0:
                    i += 1
                    brace_count += lines[i].count("{") - lines[i].count("}")

                end_line = i
                block_text = "\n".join(lines[start_line: end_line + 1])

                # Determine node type and name
                node_type = "function"
                name = Path(filepath).stem
                if "class " in stripped:
                    node_type = "class"
                    parts = stripped.split("class ")[1].split()
                    if parts:
                        name = parts[0].split("{")[0].split(":")[0].strip()
                elif "struct " in stripped:
                    node_type = "struct"
                    parts = stripped.split("struct ")[1].split()
                    if parts:
                        name = parts[0].split("{")[0].split(":")[0].strip()

                header = f"// File: {filepath} ({node_type}: {name}, lines {start_line+1}-{end_line+1})\n\n"
                documents.append(
                    Document(
                        doc_id=f"code:{filepath}::{name}:{start_line+1}",
                        text=header + block_text,
                        metadata={
                            "source": "code",
                            "filepath": filepath,
                            "language": "cpp",
                            "node_type": node_type,
                            "name": name,
                            "lineno": start_line + 1,
                            "end_lineno": end_line + 1,
                        },
                    )
                )
        i += 1

    # Fallback to generic chunking if no discrete blocks were found
    if not documents:
        return _extract_generic_nodes(source, filepath, "cpp", chunk_size, chunk_overlap)

    return documents


# ── Fortran Routine Extraction ───────────────────

def _extract_fortran_nodes(
    source: str, filepath: str, chunk_size: int = 1500, chunk_overlap: int = 200
) -> list[Document]:
    """Extract Fortran subroutines, functions, and modules."""
    lines = source.splitlines()
    if not lines:
        return []

    if len(lines) <= 30 and len(source) <= chunk_size:
        return [
            Document(
                doc_id=f"code:{filepath}",
                text=f"! File: {filepath} (Fortran)\n\n{source}",
                metadata={
                    "source": "code",
                    "filepath": filepath,
                    "language": "fortran",
                    "node_type": "file",
                    "name": Path(filepath).name,
                    "lineno": 1,
                    "end_lineno": len(lines),
                },
            )
        ]

    documents: list[Document] = []
    keywords = ("subroutine", "function", "program", "module")
    current_start = None
    current_type = None
    current_name = None

    for idx, line in enumerate(lines):
        clean = line.strip().lower()
        if not clean or clean.startswith("!"):
            continue

        if current_start is None:
            for kw in keywords:
                parts = clean.split()
                if kw in parts:
                    kw_pos = parts.index(kw)
                    if kw_pos < len(parts) - 1 and not parts[0].startswith("end"):
                        name = parts[kw_pos + 1].split("(")[0]
                        current_start = idx
                        current_type = kw
                        current_name = name
                        break
        else:
            if clean.startswith(f"end {current_type}") or clean == "end" or clean.startswith(f"end{current_type}"):
                end_idx = idx
                block_text = "\n".join(lines[current_start: end_idx + 1])
                header = f"! File: {filepath} ({current_type}: {current_name}, lines {current_start+1}-{end_idx+1})\n\n"
                documents.append(
                    Document(
                        doc_id=f"code:{filepath}::{current_name}:{current_start+1}",
                        text=header + block_text,
                        metadata={
                            "source": "code",
                            "filepath": filepath,
                            "language": "fortran",
                            "node_type": current_type,
                            "name": current_name,
                            "lineno": current_start + 1,
                            "end_lineno": end_idx + 1,
                        },
                    )
                )
                current_start = None
                current_type = None
                current_name = None

    if not documents:
        return _extract_generic_nodes(source, filepath, "fortran", chunk_size, chunk_overlap)

    return documents


# ── Generic Source Code & Markup Splitter ──────────────────────────────

def _extract_generic_nodes(
    source: str,
    filepath: str,
    language: str,
    chunk_size: int = 1500,
    chunk_overlap: int = 200,
) -> list[Document]:
    """Split generic source code, markup, or scripts into coherent chunks."""
    lines = source.splitlines()
    if not lines:
        return []

    # Small files stay intact
    if len(lines) <= 30 and len(source) <= chunk_size:
        return [
            Document(
                doc_id=f"code:{filepath}",
                text=f"# File: {filepath} ({language})\n\n{source}",
                metadata={
                    "source": "code",
                    "filepath": filepath,
                    "language": language,
                    "node_type": "file",
                    "name": Path(filepath).name,
                    "lineno": 1,
                    "end_lineno": len(lines),
                },
            )
        ]

    splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    raw_chunks = splitter.split_text(source)

    documents: list[Document] = []
    for idx, chunk in enumerate(raw_chunks, 1):
        header = f"# File: {filepath} (Language: {language}, Chunk {idx}/{len(raw_chunks)})\n\n"
        documents.append(
            Document(
                doc_id=f"code:{filepath}::chunk_{idx}",
                text=header + chunk,
                metadata={
                    "source": "code",
                    "filepath": filepath,
                    "language": language,
                    "node_type": "chunk",
                    "name": f"{Path(filepath).name}:chunk_{idx}",
                    "chunk_index": idx,
                    "total_chunks": len(raw_chunks),
                },
            )
        )

    return documents


# ── Dispatcher & Entry Points ──────────────────────────────────────────

def _extract_nodes(
    source: str,
    filepath: str,
    chunk_size: int = 1500,
    chunk_overlap: int = 200,
) -> list[Document]:
    """Dispatch extraction based on file extension and language."""
    p = Path(filepath)
    ext = p.suffix.lower()
    filename = p.name

    language = SPECIAL_FILENAMES.get(filename) or SUPPORTED_EXTENSIONS.get(ext, "generic")

    if language == "python":
        return _extract_python_nodes(source, filepath)
    elif language in ("cpp", "c", "cuda"):
        return _extract_cpp_nodes(source, filepath, chunk_size, chunk_overlap)
    elif language == "fortran":
        return _extract_fortran_nodes(source, filepath, chunk_size, chunk_overlap)
    else:
        return _extract_generic_nodes(source, filepath, language, chunk_size, chunk_overlap)


def ingest_code(
    paths: list[Path],
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    extensions: set[str] | None = None,
) -> list[Document]:
    """Ingest source code files across supported languages.

    Args:
        paths (list[Path]): Files or directories to ingest.
        chunk_size (int | None): Custom chunk size for non-AST splitters.
        chunk_overlap (int | None): Custom overlap for non-AST splitters.
        extensions (set[str] | None): Optional whitelist of extensions to ingest (e.g. {'.py', '.cpp'}).

    Returns:
        list[Document]: Extracted Documents for the RAG vector database.
    """
    effective_chunk_size = chunk_size or 1500
    effective_overlap = chunk_overlap or 200

    target_files: list[Path] = []

    for p in paths:
        if p.is_file():
            ext = p.suffix.lower()
            if (
                p.name in SPECIAL_FILENAMES
                or ext in SUPPORTED_EXTENSIONS
                or (extensions and ext in extensions)
            ):
                if ext not in _IGNORE_EXTS:
                    target_files.append(p)
        elif p.is_dir():
            for child in sorted(p.rglob("*")):
                if not child.is_file():
                    continue
                # Skip ignored directory parts
                if any(_should_skip_dir(part) for part in child.parts):
                    continue
                ext = child.suffix.lower()
                if ext in _IGNORE_EXTS:
                    continue

                if extensions:
                    if ext in extensions or child.name in SPECIAL_FILENAMES:
                        target_files.append(child)
                else:
                    if child.name in SPECIAL_FILENAMES or ext in SUPPORTED_EXTENSIONS:
                        target_files.append(child)
        else:
            logger.warning("Skipping invalid path: %s", p)

    logger.info("Found %d source file(s) across target paths.", len(target_files))

    all_docs: list[Document] = []
    for filepath_obj in target_files:
        source = _read_file(filepath_obj)
        if source is None or not source.strip():
            continue

        filepath_str = str(filepath_obj)
        docs = _extract_nodes(source, filepath_str, effective_chunk_size, effective_overlap)
        all_docs.extend(docs)
        logger.debug("Extracted %d nodes from %s", len(docs), filepath_str)

    # Ensure 100% unique document IDs across all files and AST chunks
    seen_ids: set[str] = set()
    for doc in all_docs:
        if doc.id_ in seen_ids:
            base_id = doc.id_
            counter = 1
            while f"{base_id}_{counter}" in seen_ids:
                counter += 1
            doc.id_ = f"{base_id}_{counter}"
        seen_ids.add(doc.id_)

    logger.info("Extracted %d code documents from %d files.", len(all_docs), len(target_files))
    return all_docs
