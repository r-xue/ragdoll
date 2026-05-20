"""PDF document ingestion.

Extracts text from PDF files using PyMuPDF and converts them into
document records ready for chunking and embedding.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass
class Document:
    """A normalized document record produced by any ingestor.

    Attributes
    ----------
    doc_id : str
        Unique identifier (e.g. ``pdf:<filename>`` or ``jira:CAS-1234``).
    text : str
        Full extracted text content.
    metadata : dict
        Arbitrary key/value metadata (source, page count, JIRA fields, …).
    """

    doc_id: str
    text: str
    metadata: dict = field(default_factory=dict)


def extract_pdf(path: Path) -> Document:
    """Extract all text from a single PDF file.

    Parameters
    ----------
    path : Path
        Path to the PDF file.

    Returns
    -------
    Document
        A document with ``doc_id="pdf:<stem>"``, the concatenated text
        of all pages, and metadata including page count and file path.
    """
    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    doc = pymupdf.open(str(path))
    pages_text: list[str] = []
    for page_num, page in enumerate(doc, start=1):
        text = page.get_text("text")
        if text.strip():
            pages_text.append(text)
        else:
            logger.debug("Page %d of %s is empty / image-only", page_num, path.name)

    full_text = "\n\n".join(pages_text)
    logger.info(
        "Extracted %d pages (%d chars) from %s",
        len(pages_text),
        len(full_text),
        path.name,
    )

    return Document(
        doc_id=f"pdf:{path.stem}",
        text=full_text,
        metadata={
            "source": "pdf",
            "filename": path.name,
            "filepath": str(path),
            "page_count": len(doc),
            "extracted_pages": len(pages_text),
        },
    )


def ingest_pdfs(paths: list[Path]) -> list[Document]:
    """Ingest multiple PDF files or directories of PDFs.

    Parameters
    ----------
    paths : list[Path]
        A mix of individual ``.pdf`` files and directories (which will
        be scanned recursively for ``*.pdf``).

    Returns
    -------
    list[Document]
        One document per successfully-parsed PDF.
    """
    pdf_files: list[Path] = []
    for p in paths:
        p = Path(p).expanduser().resolve()
        if p.is_file() and p.suffix.lower() == ".pdf":
            pdf_files.append(p)
        elif p.is_dir():
            pdf_files.extend(sorted(p.rglob("*.pdf")))
        else:
            logger.warning("Skipping non-PDF path: %s", p)

    if not pdf_files:
        logger.warning("No PDF files found in the given paths.")
        return []

    logger.info("Found %d PDF file(s) to ingest.", len(pdf_files))

    documents: list[Document] = []
    for pdf_path in pdf_files:
        try:
            documents.append(extract_pdf(pdf_path))
        except Exception:
            logger.exception("Failed to extract %s", pdf_path)

    logger.info("Successfully ingested %d / %d PDFs.", len(documents), len(pdf_files))
    return documents
