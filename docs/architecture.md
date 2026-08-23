# How it Works

## System Overview

Ragdoll is a **Retrieval-Augmented Generation (RAG)** system with two main
phases: **ingestion** (offline) and **query** (online).

```{mermaid}
graph LR
    classDef ai fill:#ffeb99,stroke:#ff9900,stroke-width:3px,color:#000;

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
    classDef ai fill:#ffeb99,stroke:#ff9900,stroke-width:3px,color:#000;

    subgraph Interfaces
        direction TB
        CLI[CLI / Terminal]
        WEB[Gradio Web UI]
        MCP[MCP Server<br/>Claude/VS Code]
        API[REST API / Open-WebUI]
    end

    subgraph Query Engine
        direction LR
        ROUTER{Intent Router via LLM<br/>Ollama}
        RET[Retriever]
        EMB[Embedder<br/>Ollama]
        DB[(ChromaDB)]
        LIVE[(Live APIs<br/>Jira/Bitbucket/GitHub)]
        CTX[[Context]]
        LLM((LLM<br/>Ollama))
    end

    CLI --> ROUTER
    WEB --> ROUTER
    MCP --> ROUTER
    API --> ROUTER

    ROUTER -->|Knowledge| RET
    RET --> EMB --> DB --> CTX
    ROUTER -->|Live Query| LIVE --> CTX

    CTX --> LLM --> OUT[/Streamed Answer/]

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
| -------- | -------- | -------- |
| PDF | `ingest.pdf` | One `Document` per page (PyMuPDF) |
| JIRA | `ingest.jira` | One `Document` per issue with metadata and comments |
| Bitbucket | `ingest.bitbucket` | One `Document` per PR with reviews and activity threads |
| GitHub | `ingest.github` | One `Document` per Issue/PR with comments and metadata |
| Git | `ingest.git` | One `Document` per commit with diff subject and body |
| Code | `ingest.code` | One `Document` per function/class/module docstring (AST) |

### 2. Chunking

The `chunker` module splits `Document` objects into `Chunk` objects using a
recursive character splitter. It tries to split on paragraph boundaries first,
then sentences, then words, to preserve semantic coherence.

- Default chunk size: **1000 characters**
- Default overlap: **200 characters**
- **AST-Aware Code Chunking**: When processing source code, the standard character-splitter is bypassed. Instead, Ragdoll parses the language's Abstract Syntax Tree (AST) to split code precisely at function and class boundaries. This ensures the LLM receives unbroken logical blocks of code, rather than arbitrary text slices that might cut a loop or function in half.

### 3. Embedding

Chunks are embedded in batches via Ollama's `/api/embed` endpoint using
`nomic-embed-text` (768-dimension vectors, 2048-token context).

Input sanitisation:

- Empty texts are replaced with a placeholder
- Texts exceeding 2000 characters are truncated
- Failed batches are skipped (logged) rather than crashing the pipeline

### 4. Storage (Local Embedded & Remote Client-Server)

Embeddings are stored in a ChromaDB collection with cosine similarity (`hnsw:space = "cosine"`). Ragdoll supports two storage topologies:

- **Local Embedded Mode (Default)**: Uses `chromadb.PersistentClient` pointing to SQLite files in `~/.ragdoll/data/chroma/`. Ideal for standalone workstations and offline use.
- **Remote Client-Server Mode**: Connects via `chromadb.HttpClient` to a centralized ChromaDB microservice (`chroma_host = "http://..."`). Ideal for engineering teams to prevent duplicate GPU embedding computations and share real-time index updates without copying files.

### 5. Incremental Ingestion & Change Detection

To prevent redundant LLM embedding calculations across thousands of tickets, Ragdoll implements an incremental diffing mechanism:

- **Server Namespacing**: Document IDs are namespaced as `jira-{server}-{key}` (e.g. `jira-primary-PROJ-101`), isolating records across multi-site instances and preventing cross-instance ID collisions.
- **Metadata Timestamp Diffing**: When a batch of issues is retrieved, Ragdoll checks ChromaDB for existing records using `collection.get(ids=..., include=["metadatas"])`.
- **Skipping Unchanged Nodes**: If an issue exists and its `updated` timestamp is $\le$ the timestamp recorded in ChromaDB, the issue is skipped immediately without invoking the Ollama embedding model.
- **Batched Vector Upsert**: Only newly discovered or modified issues are batched into groups of 64 and inserted via `index.insert_nodes()` for high throughput.

## Query Pipeline

### 1. Conversational Context Resolution (Query Condensation)

When conversation history is present during multi-turn chat sessions (`pixi run ragdoll chat` or Web UI), the query engine first runs a lightweight condensation step (`CONDENSE_PROMPT_TEMPLATE`). It resolves coreferences, pronouns, and implicit follow-up questions (such as *"how many of them are open?"*) into fully-specified standalone queries (*"how many open tickets in MYPROJ?"*) before passing them to the Intent Router and retrieval pipelines.

- Single-turn queries bypass condensation entirely for zero added latency.
- When active, condensation inspects the last 3 dialogue exchanges (truncated to 300 chars) for sub-second execution (~0.25s).
- When Ragdoll is accessed as an **MCP server** (`ragdoll mcp`), query condensation is bypassed completely, leaving prompt orchestration to the external host agent.

### 2. Intent Routing & Smart Server Targeting

When a query is received in interactive chat, it first passes through the **Intent Router**. The router uses the LLM to classify whether the user is asking a general conceptual/knowledge question (requiring offline vector search) or asking for a real-time list/aggregation of items from external databases.

- **Knowledge Queries (`KNOWLEDGE`)**: Routed to the ChromaDB vector database via the `VectorIndexAutoRetriever`.
- **Jira Live Queries (`JIRA_DATABASE`)**: The LLM dynamically translates natural language into a Jira JQL query. Ragdoll inspects the JQL for project keys and applies **Smart Server Routing** (matching `projects = [...]` in `config.toml`) to query only the hosting Jira instance, formatting tickets with status, type, and priority.
- **GitHub Live Queries (`GITHUB_DATABASE`)**: The LLM extracts `owner,repo,state,type` using prompt grounding with configured repositories and `github_default_owner`, querying GitHub's `/search/issues` endpoint directly.
- **Bitbucket Live Queries (`BITBUCKET_DATABASE`)**: The LLM extracts project and repository parameters and queries the Bitbucket REST API for active pull requests.

### 3. Retrieval (Knowledge Queries)

If the intent is classified as general knowledge, the **Retriever** (`VectorIndexAutoRetriever`) uses a combination of LLM reasoning and mathematical search to find the most relevant information:

1. **Query Parsing**: The generative LLM is first used to analyze your query and extract any relevant metadata filters (e.g., date ranges, Jira projects, or authors).
2. **Embedding the Query**: The user's query text is sent to an **Embedding Model** (e.g., `nomic-embed-text`) which translates the text into a mathematical vector.
3. **Vector Search**: ChromaDB performs a "nearest neighbor" mathematical search to find the top-K chunks whose vectors are closest to the query's vector, applying any filters extracted in step 1.

### 4. Generation

Retrieved chunks are formatted as context and injected into an LLM prompt:

- **Search** — returns raw chunks with scores
- **Summarize** — single-turn generation with a summarization prompt
- **Chat** — multi-turn conversation with accumulated context

## Deployment Topologies & Workload Distribution

Ragdoll is designed with a **decoupled compute architecture** that separates vector search, text embedding, and generative LLM inference. This allows engineering teams to share institutional knowledge seamlessly without requiring dedicated GPUs on the database server.

```{mermaid}
graph LR
    subgraph Client ["Client Workstation (Developer Laptop)"]
        CLI[Ragdoll CLI / Chat UI]
        LocalLLM[Local Ollama<br/>GPU / Apple Silicon Metal]
    end

    subgraph Server ["Central Server (Remote Host)"]
        ChromaSrv[ChromaDB Server<br/>Port 8000]
        HNSW[(HNSW Vector Index<br/>RAM)]
        DB[(chroma.sqlite3<br/>NVMe / SSD)]
    end

    CLI -->|1. Generate 768-dim query vector| LocalLLM
    CLI -->|2. Send 3 KB vector via HTTP POST| ChromaSrv
    ChromaSrv -->|3. Cosine distance traversal in RAM| HNSW
    ChromaSrv -->|4. Read matched text chunks| DB
    ChromaSrv -->|5. Return Top-K chunks ~5 KB| CLI
    CLI -->|6. Stream response with context| LocalLLM
```

### Workload & Resource Allocation Matrix

| Pipeline Component | Execution Location | Primary Hardware Used | Resource Profile |
| --- | --- | --- | --- |
| **Vector Storage & Similarity Search** | **Remote Chroma Server** (`chroma_host`) | **CPU + RAM + NVMe** | **Light / CPU-Bound**: ChromaDB uses CPU-based HNSW vector mathematics in RAM. **Requires 0 GPU**. |
| **Chat / LLM Token Generation** | **Local Laptop** (or custom `ollama_host`) | **GPU / Unified Memory** | **Heavy / VRAM-Bound**: Generates tokens using Apple Silicon Metal or NVIDIA Tensor Cores. |
| **Query Embedding Calculation** | **Local Laptop** (or custom `ollama_host`) | **GPU / CPU** | **Negligible**: Embeds a single 1-line query in **< 10 ms**. |
| **Bulk Ingestion Embedding** | **Machine running Ingest command** | **GPU** | **Heavy / GPU-Bound**: Embeds thousands of text chunks in batches during initial indexing. |
| **Document Parsing & AST Splitting** | **Client Machine** | **CPU + RAM** | **Light / CPU-Bound**: Parses ASTs, Git logs, and PDFs into structured chunks. |

### Supported Deployment Topologies

#### 1. Hybrid Mode (Recommended Team Architecture)

- **Central Server**: Lightweight Linux VM running `pixi run ragdoll serve-chroma` (2–4 vCPUs, 8 GB RAM, standard SSD, **no GPU required**).
- **Developer Laptops**: Run local Ollama instances (`qwen3.8:27b-mlx`, `gemma4:12b`, etc.) for private, zero-latency local token generation while querying the shared organizational knowledge base.

```toml
# ~/.ragdoll/config.toml on developer laptop
ollama_host = "http://localhost:11434"
chroma_host = "http://ragdoll-server.internal"
chroma_port = 8000
```

#### 2. Fully Centralized "Thin Client" Mode

- **Central Multi-GPU Server**: Hosts both the ChromaDB server and high-capacity Ollama instance (`qwen3.8:27b` on dual RTX 3090/4090 or A100).
- **Developer Laptops**: Perform **zero AI computation**. All inference, embedding, and vector search occur remotely.

```toml
# ~/.ragdoll/config.toml on developer laptop
ollama_host = "http://gpu-server.internal:11434"
chroma_host = "http://gpu-server.internal:8000"
```

#### 3. Dedicated Ingestion Worker + Read-Only Team Readers

- **Nightly Ingestion Worker**: A dedicated build runner or cron job with GPU access executes daily ingestion scripts (`pixi run ragdoll ingest jira ...`) against the central ChromaDB server.
- **Team Members**: Only perform read queries (`chat`, `search`), consuming negligible server resources (< 10ms per query) without local indexing overhead.

### Network Bandwidth & Latency Footprint

Because Ragdoll transfers only mathematical vectors and small text chunks over HTTP, network overhead is minimal:

- **Query Payload (Outbound to Server)**: ~3.1 KB (768 32-bit floating-point numbers + metadata).
- **Search Result (Inbound to Client)**: ~4.5–8.0 KB (Top-5 chunk text strings and metadata dictionaries).
- **Network Latency Impact**: < 2 ms overhead on standard Gigabit corporate LAN or Wi-Fi.

## Local Storage Layout

```
~/.ragdoll/
├── config.toml       # User-level configuration (chmod 600)
├── chat_history      # Readline history for chat (last 500 queries)
└── data/
    └── chroma/       # ChromaDB persistent storage
```
