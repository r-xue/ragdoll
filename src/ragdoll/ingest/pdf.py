"""PDF ingestion pipeline via LlamaIndex.

Loads PDF documents, parses text, and indexes them into the vector store.
"""

import logging
from pathlib import Path
from llama_index.core import SimpleDirectoryReader

from ragdoll.store.vectordb import get_index

logger = logging.getLogger(__name__)


def ingest_pdfs(directory: str | Path) -> int:
    """Ingest all PDFs from a directory into the vector store.

    Args:
        directory (str or Path): Directory containing PDF files.

    Returns:
        int: Number of chunks upserted.
    """
    directory = Path(directory)
    if not directory.is_dir():
        logger.error("Invalid directory: %s", directory)
        return 0

    logger.info("Loading PDFs from %s using LlamaIndex...", directory)

    # SimpleDirectoryReader automatically uses PyMuPDF or pdfminer
    # based on what's installed, and handles page-level metadata.
    reader = SimpleDirectoryReader(
        input_dir=str(directory),
        required_exts=[".pdf"],
        recursive=True
    )

    documents = reader.load_data()

    if not documents:
        logger.warning("No PDF documents found or loaded.")
        return 0

    # We add a custom metadata field for source tracking
    for doc in documents:
        doc.metadata["source"] = "pdf"

    logger.info("Loaded %d document nodes/pages. Indexing into vector store...", len(documents))

    from rich.progress import (
        Progress,
        TextColumn,
        BarColumn,
        TaskProgressColumn,
        MofNCompleteColumn,
        TimeRemainingColumn,
    )
    from rich.console import Console

    console = Console()
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
        task = progress.add_task("Embedding PDFs...", total=len(documents))
        for doc in documents:
            index.insert(doc)
            progress.advance(task)

    logger.info("Successfully ingested PDF documents.")
    return len(documents)
