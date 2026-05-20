# Architecture

## System Overview

Ragdoll is a **Retrieval-Augmented Generation (RAG)** system with two main
phases: **ingestion** (offline) and **query** (online).

```
                         Ingestion Pipeline
                         ──────────────────
  ┌──────────┐
  │ PDF      │──┐
  │ JIRA     │──┼──→  Ingestor  →  Chunker  →  Embedder  →  ChromaDB
  │ Code     │──┘               (AST-aware)   (Ollama)     (persistent)
  └──────────┘

                         Query Pipeline
                         ──────────────
  ┌──────────┐
  │ CLI      │──→  Embed query  →  Retriever  →  Context chunks
  │ Chat     │                                        │
  └──────────┘                                        ▼
                                               LLM (Ollama)
                                                     │
                                                     ▼
                                              Streamed answer
```

## Module Map

```
src/ragdoll/
├── __init__.py          # Package metadata
├── config.py            # Pydantic Settings (4-layer precedence)
├── cli.py               # Click CLI with Rich formatting
├── ingest/
│   ├── pdf.py           # PyMuPDF text extraction
│   ├── jira.py          # JIRA REST API client
│   ├── code.py          # AST-based Python code parser
│   └── chunker.py       # Recursive character text splitter
├── llm/
│   └── ollama.py        # Ollama HTTP client (embed, generate, chat)
├── store/
│   └── vectordb.py      # ChromaDB wrapper (upsert, query, manage)
└── query/
    ├── retriever.py     # Semantic search with source filtering
    └── rag.py           # RAG chains (ask, summarize, chat)
```

## Ingestion Pipeline

### 1. Source Extraction

Each data source has a dedicated ingestor that produces `Document` objects:

| Source | Module | Output |
|--------|--------|--------|
| PDF | `ingest.pdf` | One `Document` per page (PyMuPDF) |
| JIRA | `ingest.jira` | One `Document` per issue (structured text) |
| Code | `ingest.code` | One `Document` per function/class/module docstring (AST) |

### 2. Chunking

The `chunker` module splits `Document` objects into `Chunk` objects using a
recursive character splitter. It tries to split on paragraph boundaries first,
then sentences, then words, to preserve semantic coherence.

- Default chunk size: **1000 characters**
- Default overlap: **200 characters**
- Code chunks respect function/class boundaries from AST parsing

### 3. Embedding

Chunks are embedded in batches via Ollama's `/api/embed` endpoint using
`nomic-embed-text` (768-dimension vectors, 2048-token context).

Input sanitisation:
- Empty texts are replaced with a placeholder
- Texts exceeding 2000 characters are truncated
- Failed batches are skipped (logged) rather than crashing the pipeline

### 4. Storage

Embeddings are stored in a persistent ChromaDB collection with cosine
similarity. Each chunk's metadata (source type, file path, JIRA key, etc.)
is stored alongside the embedding for filtering.

## Query Pipeline

### 1. Retrieval

1. The query text is embedded using the same model
2. ChromaDB finds the top-K nearest chunks by cosine similarity
3. Optional metadata filtering narrows results to a specific source type

### 2. Generation

Retrieved chunks are formatted as context and injected into an LLM prompt:

- **Search** — returns raw chunks with scores
- **Summarize** — single-turn generation with a summarization prompt
- **Chat** — multi-turn conversation with accumulated context

## Data Flow

```
User input
  │
  ▼
embed(query) ──→ ChromaDB.query(top_k=8) ──→ [chunk₁, chunk₂, ..., chunk₈]
                                                       │
                                                       ▼
                                              Format as context
                                                       │
                                                       ▼
                                              LLM.generate(context + prompt)
                                                       │
                                                       ▼
                                              Stream tokens to terminal
```

## Local Storage Layout

```
~/.ragdoll/
├── config.toml       # User-level configuration (chmod 600)
├── chat_history      # Readline history for chat (last 500 queries)
└── data/
    └── chroma/       # ChromaDB persistent storage
```
