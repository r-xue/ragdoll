"""Incremental PDF ingestion pipeline via LlamaIndex.

Loads PDF documents, computes content hashes, checks existing ChromaDB records,
bypasses unmodified files, and re-indexes modified/new PDFs.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from llama_index.core import SimpleDirectoryReader
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from ragdoll.config import settings
from ragdoll.store.vectordb import _get_client, get_index

logger = logging.getLogger(__name__)
console = Console()


def _compute_sha256(file_path: Path) -> str:
    """Compute SHA256 checksum of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def ingest_pdfs(
    paths: str | Path | list[str | Path],
    force: bool = False,
) -> tuple[int, int]:
    """Ingest PDFs into the vector store with incremental content-hash change detection.

    Args:
        paths (str | Path | list[str | Path]): Directory or file path(s) containing PDF files.
        force (bool): If True, re-indexes all PDFs even if already present and unchanged.

    Returns:
        tuple[int, int]: (newly_ingested_chunks_count, skipped_up_to_date_files_count)
    """
    # 1. Collect all PDF files
    if isinstance(paths, (str, Path)):
        input_paths = [Path(paths)]
    else:
        input_paths = [Path(p) for p in paths]

    pdf_files: list[Path] = []
    for p in input_paths:
        p_resolved = p.resolve()
        if p_resolved.is_file() and p_resolved.suffix.lower() == ".pdf":
            pdf_files.append(p_resolved)
        elif p_resolved.is_dir():
            pdf_files.extend(sorted(p_resolved.rglob("*.pdf")))

    # Deduplicate files
    pdf_files = sorted(list(dict.fromkeys(pdf_files)))

    if not pdf_files:
        logger.warning("No PDF documents found in specified path(s).")
        return (0, 0)

    # 2. Fetch existing PDF metadata from ChromaDB for incremental comparison
    client = _get_client()
    chroma_col = client.get_or_create_collection(settings.collection_name)

    indexed_files: dict[str, set[str]] = {}
    if not force:
        try:
            records = chroma_col.get(
                where={"source": "pdf"},
                include=["metadatas"],
            )
            if records and records.get("metadatas"):
                for meta in records["metadatas"]:
                    if not meta:
                        continue
                    fpath = meta.get("file_path")
                    fhash = meta.get("file_hash")
                    if fpath:
                        if fpath not in indexed_files:
                            indexed_files[fpath] = set()
                        if fhash:
                            indexed_files[fpath].add(fhash)
        except Exception as e:
            logger.debug("ChromaDB PDF metadata lookup notice: %s", e)

    # 3. Filter files into (to_index, skipped)
    files_to_index: list[tuple[Path, str]] = []
    skipped_files: list[Path] = []

    for pdf_path in pdf_files:
        fpath_str = str(pdf_path.resolve())
        current_hash = _compute_sha256(pdf_path)

        if not force and fpath_str in indexed_files and current_hash in indexed_files[fpath_str]:
            skipped_files.append(pdf_path)
        else:
            # If the file exists in ChromaDB but hash differs, purge old chunks first
            if fpath_str in indexed_files:
                try:
                    chroma_col.delete(where={"$and": [{"source": "pdf"}, {"file_path": fpath_str}]})
                    logger.info("Purged outdated ChromaDB chunks for modified PDF: %s", pdf_path.name)
                except Exception as e:
                    logger.debug("Failed to purge stale PDF chunks for %s: %s", fpath_str, e)

            files_to_index.append((pdf_path, current_hash))

    skipped_count = len(skipped_files)
    logger.info(
        "Scanned %d PDF(s): %d new/updated to index, %d already up-to-date in ChromaDB.",
        len(pdf_files),
        len(files_to_index),
        skipped_count,
    )

    if not files_to_index:
        return (0, skipped_count)

    # 4. Load and parse only new/updated PDFs
    all_documents = []
    for pdf_path, fhash in files_to_index:
        try:
            reader = SimpleDirectoryReader(
                input_files=[str(pdf_path)],
                required_exts=[".pdf"],
            )
            docs = reader.load_data()
            mtime = pdf_path.stat().st_mtime
            for doc in docs:
                doc.metadata["source"] = "pdf"
                doc.metadata["file_path"] = str(pdf_path.resolve())
                doc.metadata["file_name"] = pdf_path.name
                doc.metadata["file_hash"] = fhash
                doc.metadata["mtime_ts"] = mtime
            all_documents.extend(docs)
        except Exception as e:
            logger.error("Failed to load PDF %s: %s", pdf_path, e)

    if not all_documents:
        return (0, skipped_count)

    # 5. Embed and insert into ChromaDB index with Rich progress bar
    index = get_index()
    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=35),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Embedding PDFs...", total=len(all_documents))
        for doc in all_documents:
            index.insert(doc)
            progress.advance(task)

    logger.info("Successfully ingested %d new/updated PDF chunk(s).", len(all_documents))
    return (len(all_documents), skipped_count)
