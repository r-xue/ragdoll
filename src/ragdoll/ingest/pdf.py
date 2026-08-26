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
            page_size = 2000
            offset = 0
            while True:
                records = chroma_col.get(
                    where={"source": "pdf"},
                    include=["metadatas"],
                    limit=page_size,
                    offset=offset,
                )
                if not records or not records.get("metadatas"):
                    break
                metas = records["metadatas"]
                for meta in metas:
                    if not meta:
                        continue
                    fpath = meta.get("file_path")
                    fhash = meta.get("file_hash")
                    if fpath:
                        if fpath not in indexed_files:
                            indexed_files[fpath] = set()
                        if fhash:
                            indexed_files[fpath].add(fhash)
                offset += len(metas)
                if len(metas) < page_size:
                    break
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

    console.print(f"  -> Parsing [bold]{len(files_to_index)}[/bold] new/modified PDF(s) ({skipped_count} up-to-date skipped)...")

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
            for i, doc in enumerate(docs, 1):
                doc.id_ = f"pdf:{pdf_path.resolve()}::page_{i}"
                doc.metadata["source"] = "pdf"
                doc.metadata["file_path"] = str(pdf_path.resolve())
                doc.metadata["file_name"] = pdf_path.name
                doc.metadata["file_hash"] = fhash
                doc.metadata["mtime_ts"] = mtime
            all_documents.extend(docs)
        except Exception as e:
            console.print(f"  [yellow]Warning:[/yellow] Failed to load PDF [bold]{pdf_path.name}[/bold]: {e}")
            logger.error("Failed to load PDF %s: %s", pdf_path, e)

    if not all_documents:
        return (0, skipped_count)

    console.print(f"  -> Extracted [green]{len(all_documents)}[/green] page node(s). Computing embeddings via Ollama...")

    # 5. Embed and insert into ChromaDB index with Rich progress bar
    #    GracefulInterrupt defers ^C until the current insert() finishes,
    #    preventing HNSW index corruption in ChromaDB's Rust backend.
    from ragdoll.store.safety import GracefulInterrupt

    ingested = 0
    batch_embed_size = 50
    batch_ranges = list(range(0, len(all_documents), batch_embed_size))

    try:
        index = get_index()
        with GracefulInterrupt() as gi, Progress(
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=35),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task("Embedding PDFs...", total=len(all_documents))
            for i in batch_ranges:
                batch_docs = all_documents[i : i + batch_embed_size]
                index.insert_nodes(batch_docs)
                ingested += len(batch_docs)
                progress.advance(task, advance=len(batch_docs))
                if gi.interrupted:
                    break
    except KeyboardInterrupt:
        console.print(f"  [yellow]Partially ingested {ingested}/{len(all_documents)} PDF chunk(s) before interrupt.[/yellow]")
        return (ingested, skipped_count)
    except Exception as e:
        console.print(f"  [bold red]Embedding Error:[/bold red] {e}")
        logger.exception("PDF embedding failed: %s", e)
        raise

    logger.info("Successfully ingested %d new/updated PDF chunk(s).", ingested)
    return (ingested, skipped_count)
