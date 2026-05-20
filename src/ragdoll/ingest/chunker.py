"""Text chunking for the ingestion pipeline.

Implements a recursive character text splitter that produces overlapping
chunks suitable for embedding and retrieval.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ragdoll.config import settings
from ragdoll.ingest.pdf import Document

logger = logging.getLogger(__name__)

# Separators tried in order — prefer splitting on paragraph / sentence
# boundaries before falling back to words / characters.
DEFAULT_SEPARATORS = ["\n\n", "\n", ". ", ", ", " ", ""]


@dataclass
class Chunk:
    """A single text chunk with provenance metadata.

    Attributes:
        chunk_id (str): Unique identifier: ``<doc_id>:<chunk_index>``.
        text (str): The chunk text.
        metadata (dict): Inherited document metadata plus ``chunk_index``.
    """

    chunk_id: str
    text: str
    metadata: dict = field(default_factory=dict)


def _split_text(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    separators: list[str] | None = None,
) -> list[str]:
    """Recursively split *text* into pieces of at most *chunk_size* characters.

    The algorithm tries each separator in order. For the first separator
    that produces segments, it merges adjacent segments back together up
    to *chunk_size* while respecting *chunk_overlap*.
    """
    if separators is None:
        separators = DEFAULT_SEPARATORS

    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    # Find the first separator that actually splits the text.
    chosen_sep = ""
    for sep in separators:
        if sep == "":
            chosen_sep = sep
            break
        if sep in text:
            chosen_sep = sep
            break

    # Split on chosen separator.
    if chosen_sep:
        segments = text.split(chosen_sep)
    else:
        # Character-level split as last resort.
        segments = list(text)

    # Merge segments back together up to chunk_size.
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for segment in segments:
        seg_len = len(segment) + (len(chosen_sep) if current else 0)

        if current_len + seg_len > chunk_size and current:
            chunk_text = chosen_sep.join(current)
            if chunk_text.strip():
                chunks.append(chunk_text)

            # Keep tail segments for overlap.
            overlap_text = ""
            while current and len(overlap_text) < chunk_overlap:
                overlap_text = chosen_sep.join(current[-1:]) + chosen_sep + overlap_text
                current.pop()
            current = []
            current_len = 0

            # If the segment itself is larger than chunk_size, recurse.
            if len(segment) > chunk_size:
                remaining_seps = separators[separators.index(chosen_sep) + 1 :] if chosen_sep in separators else separators[1:]
                sub_chunks = _split_text(segment, chunk_size, chunk_overlap, remaining_seps)
                chunks.extend(sub_chunks)
                continue

        current.append(segment)
        current_len += seg_len

    # Flush remaining.
    if current:
        chunk_text = chosen_sep.join(current)
        if chunk_text.strip():
            chunks.append(chunk_text)

    return chunks


def chunk_document(
    doc: Document,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[Chunk]:
    """Split a Document into overlapping Chunks.

    Args:
        doc (Document): The source document.
        chunk_size (int, optional): Max characters per chunk (default: from settings).
        chunk_overlap (int, optional): Overlap between consecutive chunks (default: from settings).

    Returns:
        list[Chunk]: Ordered list of chunks with inherited metadata.
    """
    size = chunk_size or settings.chunk_size
    overlap = chunk_overlap or settings.chunk_overlap

    raw_chunks = _split_text(doc.text, size, overlap)

    chunks: list[Chunk] = []
    for idx, text in enumerate(raw_chunks):
        chunk = Chunk(
            chunk_id=f"{doc.doc_id}:{idx}",
            text=text.strip(),
            metadata={
                **doc.metadata,
                "doc_id": doc.doc_id,
                "chunk_index": idx,
            },
        )
        chunks.append(chunk)

    logger.debug(
        "Chunked %s → %d chunks (size=%d, overlap=%d)",
        doc.doc_id,
        len(chunks),
        size,
        overlap,
    )
    return chunks


def chunk_documents(
    docs: list[Document],
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[Chunk]:
    """Chunk a list of Documents.

    Args:
        docs (list[Document]): Documents to chunk.
        chunk_size (int, optional): Max characters per chunk.
        chunk_overlap (int, optional): Overlap between consecutive chunks.

    Returns:
        list[Chunk]: All chunks from all documents, in order.
    """
    all_chunks: list[Chunk] = []
    for doc in docs:
        all_chunks.extend(chunk_document(doc, chunk_size, chunk_overlap))
    logger.info(
        "Chunked %d documents into %d total chunks.", len(docs), len(all_chunks)
    )
    return all_chunks
