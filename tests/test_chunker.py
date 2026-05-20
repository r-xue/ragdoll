"""Tests for the text chunker."""

from ragdoll.ingest.chunker import Chunk, chunk_document, _split_text
from ragdoll.ingest.pdf import Document


def test_split_text_short():
    """Text shorter than chunk_size should return as-is."""
    result = _split_text("Hello world", chunk_size=100, chunk_overlap=20)
    assert result == ["Hello world"]


def test_split_text_paragraph_boundary():
    """Should prefer splitting on paragraph boundaries."""
    text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
    result = _split_text(text, chunk_size=30, chunk_overlap=5)
    assert len(result) >= 2
    assert all(len(chunk) <= 30 for chunk in result)


def test_split_text_empty():
    """Empty text should return empty list."""
    result = _split_text("", chunk_size=100, chunk_overlap=20)
    assert result == []


def test_chunk_document():
    """chunk_document should produce Chunk objects with correct IDs."""
    doc = Document(
        doc_id="test:doc1",
        text="A" * 500 + "\n\n" + "B" * 500,
        metadata={"source": "test"},
    )
    chunks = chunk_document(doc, chunk_size=200, chunk_overlap=50)
    assert len(chunks) > 1
    assert all(isinstance(c, Chunk) for c in chunks)
    assert chunks[0].chunk_id.startswith("test:doc1:")
    assert chunks[0].metadata["source"] == "test"
    assert chunks[0].metadata["doc_id"] == "test:doc1"


def test_chunk_document_preserves_metadata():
    """Chunk metadata should include inherited doc metadata + chunk_index."""
    doc = Document(
        doc_id="test:meta",
        text="Short text",
        metadata={"source": "test", "custom_key": "custom_value"},
    )
    chunks = chunk_document(doc, chunk_size=1000, chunk_overlap=100)
    assert len(chunks) == 1
    assert chunks[0].metadata["custom_key"] == "custom_value"
    assert chunks[0].metadata["chunk_index"] == 0
