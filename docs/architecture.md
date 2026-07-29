# How it Works

## System Overview

Ragdoll is a **Retrieval-Augmented Generation (RAG)** system with two main
phases: **ingestion** (offline) and **query** (online).

```{mermaid}
graph LR
    classDef ai fill:#e1d5e7,stroke:#9673a6,stroke-width:2px,color:#000;

    subgraph Sources
        direction TB
        PDF[PDF]
        JIRA[JIRA]
        BB[Bitbucket PRs]
        GIT[Git Commits]
        CODE[Source Code]
    end
    
    subgraph Ingestion Pipeline
        direction LR
        INGEST[Ingestor]
        CHUNK[Chunker<br/>AST-aware]
        EMBED[Embedder<br/>Ollama]
        DB[(ChromaDB<br/>persistent)]
    end
    
    PDF --> INGEST
    JIRA --> INGEST
    BB --> INGEST
    GIT --> INGEST
    CODE --> INGEST
    
    INGEST --> CHUNK
    CHUNK --> EMBED
    EMBED --> DB

    class EMBED ai;
```

```{mermaid}
graph LR
    classDef ai fill:#e1d5e7,stroke:#9673a6,stroke-width:2px,color:#000;

    subgraph Interfaces
        direction TB
        CLI[CLI / Terminal]
        WEB[Gradio Web UI]
        MCP[MCP Server<br/>Claude/VS Code]
        API[REST API / Open-WebUI]
    end

    subgraph Query Engine
        direction LR
        ROUTER{Intent Router}
        RET[Retriever]
        EMB[Embedder<br/>Ollama]
        DB[(ChromaDB)]
        LIVE[(Live APIs<br/>Jira/Bitbucket)]
        CTX[[Context]]
        LLM((LLM<br/>Ollama))
    end

    CLI --> ROUTER
    WEB --> ROUTER
    MCP --> ROUTER
    API --> ROUTER

    ROUTER -->|Knowledge| RET
    RET --> EMB
    EMB --> DB
    DB --> CTX
    
    ROUTER -->|Live Query| LIVE
    LIVE --> CTX

    CTX --> LLM
    LLM --> OUT[/Streamed Answer/]

    class EMB,LLM,ROUTER ai;
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

### 1. Intent Routing

When a query is received, it first passes through the **Intent Router**. The router uses the LLM to classify whether the user is asking a general knowledge question (requiring vector search) or asking for a list/aggregation of items from a live database (like Jira tickets or Bitbucket PRs).

- **Knowledge Queries**: Routed to the standard vector database (ChromaDB) via the Retriever.
- **Live Queries**: The LLM automatically translates the natural language into an API query (like Jira JQL) and fetches results directly from the live external API, skipping the vector database entirely.

### 2. Retrieval (Knowledge Queries)

If the intent is classified as general knowledge, the **Retriever** (`VectorIndexAutoRetriever`) uses a combination of LLM reasoning and mathematical search to find the most relevant information:

1. **Query Parsing**: The generative LLM is first used to analyze your query and extract any relevant metadata filters (e.g., date ranges, Jira projects, or authors).
2. **Embedding the Query**: The user's query text is sent to an **Embedding Model** (e.g., `nomic-embed-text`) which translates the text into a mathematical vector.
3. **Vector Search**: ChromaDB performs a "nearest neighbor" mathematical search to find the top-K chunks whose vectors are closest to the query's vector, applying any filters extracted in step 1.

### 3. Generation

Retrieved chunks are formatted as context and injected into an LLM prompt:

- **Search** — returns raw chunks with scores
- **Summarize** — single-turn generation with a summarization prompt
- **Chat** — multi-turn conversation with accumulated context


## Local Storage Layout

```
~/.ragdoll/
├── config.toml       # User-level configuration (chmod 600)
├── chat_history      # Readline history for chat (last 500 queries)
└── data/
    └── chroma/       # ChromaDB persistent storage
```
