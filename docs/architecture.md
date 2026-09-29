# How it Works

## System Overview

Ragdoll is a **Retrieval-Augmented Generation (RAG)** system with two main
phases: **ingestion** (offline) and **query** (online).

```{mermaid}
graph LR
    classDef ai fill:#ffeb99,stroke:#ff9900,stroke-width:3px,color:#000;

    subgraph Sources
        direction TB
        PDF[PDF Documents]
        JIRA[JIRA Issues]
        CONF[Confluence Spaces]
        BB[Bitbucket PRs]
        GITHUB[GitHub PRs & Issues]
        GIT[Git Commits]
        CODE[Source Code]
    end
    
    subgraph Ingestion Pipeline
        direction LR
        INGEST[Ingestors]
        CHUNK[Chunking<br/>AST & Sentences]
        EMBED[Embedder<br/>Ollama]
        DB[(ChromaDB<br/>persistent)]
    end
    
    PDF --> INGEST
    JIRA --> INGEST
    CONF --> INGEST
    BB --> INGEST
    GITHUB --> INGEST
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
├── api.py               # FastAPI REST endpoints
├── mcp.py               # Model Context Protocol (FastMCP) server
├── ui.py                # Rich terminal & Gradio Web UI
├── ingest/
│   ├── pdf.py           # PDF document extraction (SimpleDirectoryReader)
│   ├── jira.py          # JIRA REST API client & changelog ingestion
│   ├── confluence.py    # Confluence space & XHTML page parser
│   ├── bitbucket.py     # Bitbucket PR, diff & comment ingestion
│   ├── github.py        # GitHub PR, issue & discussion ingestion
│   ├── git.py           # Git commit history & diff parser
│   ├── code.py          # Multi-language code parser (AST & structural)
│   └── staging.py       # Manifest-driven local staging scanner
├── llm/
│   └── ollama.py        # Ollama HTTP client (embed, generate, chat)
├── store/
│   ├── vectordb.py      # ChromaDB wrapper (upsert, query, manage)
│   └── safety.py        # Database integrity (GracefulInterrupt, health checks)
└── query/
    ├── retriever.py     # Semantic search with source filtering
    └── rag.py           # RAG chains (query, summarize, chat, intent routing)
```

## Ingestion Pipeline

### 1. Source Extraction

Each data source has a dedicated ingestor that produces LlamaIndex `Document` objects:

| Source | Module | Output |
| -------- | -------- | -------- |
| PDF | `ingest.pdf` | One `Document` per page via LlamaIndex (`SimpleDirectoryReader`) |
| JIRA | `ingest.jira` | One `Document` per issue with metadata and comments |
| Confluence | `ingest.confluence` | One `Document` per wiki page with comments and space metadata |
| Bitbucket | `ingest.bitbucket` | One `Document` per PR with reviews, activity threads, and diffs |
| GitHub | `ingest.github` | One `Document` per Issue/PR with comments and metadata |
| Git | `ingest.git` | One `Document` per commit with diff subject and body |
| Code | `ingest.code` | Multi-language code units: AST-parsed Python, structural C/C++/Fortran/Shell/CMake |

### 2. Chunking

Text documents are chunked using LlamaIndex's [`SentenceSplitter`](https://docs.llamaindex.ai/en/stable/api_reference/node_parsers/sentence_splitter/), preserving natural sentence and paragraph boundaries rather than arbitrary character cuts.

- Default chunk size: **1000 characters** (`settings.chunk_size`)
- Default overlap: **200 characters** (`settings.chunk_overlap`)
- **AST-Aware Code Chunking**: When processing source code, character-based splitting is bypassed. For Python, Ragdoll parses the language's [Abstract Syntax Tree (AST)](https://docs.python.org/3/library/ast.html) to split code precisely at function and class boundaries. For other supported languages (C/C++, Fortran, Shell, CMake), structural block boundaries are used so that the LLM receives unbroken logical blocks of code.

### 3. Embedding & Ingestion Sanitization

Chunks are embedded in batches via Ollama's `/api/embed` endpoint using
[`nomic-embed-text`](https://arxiv.org/abs/2402.01613) (768-dimension vectors, up to 8192-token context) or equivalent local embedding models.

Before chunks are embedded, Ragdoll applies strict input sanitization to ensure data quality and system security:

- **Markup & Boilerplate Stripping**: Removes raw HTML/XHTML wrappers, layout tables, and platform macro boilerplate (such as `{code}`, `{panel}`, or Confluence storage format artifacts) while preserving substantive code and text blocks.
- **Binary & Media Exclusion**: Automatically discards inline base64 image data, large binary blobs, and hex dumps that waste context tokens and degrade embedding vector geometry.
- **Thread & Signature Pruning**: Cleans repetitive email signatures, automated bot status notifications (e.g., automated build alerts), and boilerplate legal disclaimers.
- **[Indirect Prompt Injection (IPI)](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) Neutralization**: Scans incoming content for prompt override strings (e.g., `"IGNORE ALL PREVIOUS INSTRUCTIONS"`) and escapes or neutralizes control sequences before they enter the vector index (see [OWASP LLM01](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)).
- **Batching & Length Safeguards**: Empty texts are replaced with placeholders, texts exceeding model token windows are cleanly truncated, and failed batch requests are logged and skipped without halting ingestion.

### 4. Storage (Local Embedded & Remote Client-Server)

Embeddings are stored in a ChromaDB collection with cosine similarity over a [Hierarchical Navigable Small World (HNSW)](https://arxiv.org/abs/1603.09320) graph (`hnsw:space = "cosine"`). Ragdoll supports two storage topologies:

- **Local Embedded Mode (Default)**: Uses `chromadb.PersistentClient` pointing to SQLite files in `~/.ragdoll/data/chroma/`. Ideal for standalone workstations and offline use.
- **Remote Client-Server Mode**: Connects via `chromadb.HttpClient` to a centralized ChromaDB microservice (`chroma_host = "http://..."`). Ideal for engineering teams to prevent duplicate GPU embedding computations and share real-time index updates without copying files.

### 5. Incremental Ingestion & Change Detection

To prevent redundant LLM embedding calculations across thousands of tickets, Ragdoll implements an incremental diffing mechanism:

- **Server Namespacing**: Document IDs are namespaced as `jira-{server}-{key}` (e.g. `jira-primary-PROJ-101`), isolating records across multi-site instances and preventing cross-instance ID collisions.
- **Metadata Timestamp Diffing**: When a batch of issues is retrieved, Ragdoll checks ChromaDB for existing records using `collection.get(ids=..., include=["metadatas"])`.
- **Skipping Unchanged Nodes**: If an issue exists and its `updated` timestamp is <= the timestamp recorded in ChromaDB, the issue is skipped immediately without invoking the Ollama embedding model.
- **Batched Vector Upsert**: Only newly discovered or modified issues are batched into groups of 50 and inserted via `index.insert_nodes()` wrapped in `GracefulInterrupt` for high throughput and write safety.

## Query Pipeline

### 1. Conversational Context Resolution (Query Condensation)

When conversation history is present during multi-turn chat sessions (`pixi run ragdoll chat` or Web UI), the query engine first runs a lightweight condensation step (`CONDENSE_PROMPT_TEMPLATE`). It resolves coreferences, pronouns, and implicit follow-up questions (such as *"how many of them are open?"*) into fully-specified standalone queries (*"how many open tickets in MYPROJ?"*) before passing them to the Intent Router and retrieval pipelines.

- Single-turn queries bypass condensation entirely for zero added latency.
- When active, condensation inspects the last 3 dialogue exchanges (truncated to 300 chars) for sub-second execution (~0.25s).
- When Ragdoll is accessed as an **MCP server** (`ragdoll mcp`), query condensation is bypassed completely, leaving prompt orchestration to the external host agent.

### 2. Intent Routing & Smart Server Targeting

When a query is received in interactive chat, it first passes through the **Intent Router**. The router uses the LLM to classify whether the user is asking a general conceptual/knowledge question (requiring offline vector search) or asking for a real-time list/aggregation of items from external databases.

- **Knowledge Queries (`KNOWLEDGE`)**: Routed to the ChromaDB vector database via LlamaIndex vector retrieval.
- **Jira Live Queries (`JIRA_DATABASE`)**: The LLM dynamically translates natural language into a high-recall Jira JQL query. Ragdoll inspects the JQL for project keys and applies **Smart Server Routing** (matching `projects = [...]` in `config.toml`) to query only the hosting Jira instance, extracting issue status, priority, components, labels, and description previews.
- **GitHub Live Queries (`GITHUB_DATABASE`)**: The LLM extracts `owner,repo,state,type` using prompt grounding with configured repositories and `github_default_owner`, querying GitHub's `/search/issues` endpoint directly.
- **Bitbucket Live Queries (`BITBUCKET_DATABASE`)**: The LLM extracts project and repository parameters and queries the Bitbucket REST API for active pull requests.

### 3. Retrieval Strategy: Intent-Driven Hybrid Search

Technical assistance in software engineering requires both **real-time accuracy** (e.g. ticket states, open pull requests, live assignments) and **deep semantic recall** (e.g. architectural rationale, historical bug fixes, algorithm explanations). Ragdoll addresses this via an **intent-driven hybrid retrieval strategy**:

```{mermaid}
flowchart TD
    QUERY["User Query"]

    ROUTER{"Intent Router<br/>(Ollama LLM)"}
    QUERY --> ROUTER

    subgraph KNOWLEDGE["Knowledge Retrieval Path"]
        direction TB
        EMBED["Query Embedding<br/>(nomic-embed-text)"]
        VEC[("ChromaDB Vector Store<br/>(HNSW Cosine)")]
        TOPK_D["Top-k Semantic Chunks"]
        EMBED --> VEC --> TOPK_D
    end

    subgraph LIVE["Live Database Retrieval Path"]
        direction TB
        PARAM["Dynamic Query Generator<br/>(JQL / REST API Params)"]
        APIS[("Live Platform APIs<br/>Jira / GitHub / Bitbucket")]
        LIVE_RES["Real-Time API Results"]
        PARAM --> APIS --> LIVE_RES
    end

    ROUTER -->|Knowledge Intent| EMBED
    ROUTER -->|Live Query Intent| PARAM

    TOPK_D --> FUSION
    LIVE_RES --> FUSION

    FUSION["Hybrid Context Fusion & Deduplication<br/>(Enrich live tickets with semantic vector hits)"]
    FUSION --> CTX["Delimited Context Block<br/>--- CONTEXT ---"]
    CTX --> LLM["Generation LLM<br/>(Ollama)"]
    LLM --> OUT["Streamed Response with Citations"]
```

1. **Dense Semantic Search (Vector Space)**:
   - For conceptual inquiries (e.g., *"how are worker retry strategies handled?"*), queries are routed to ChromaDB via LlamaIndex's [`VectorIndexRetriever`](https://docs.llamaindex.ai/en/stable/api_reference/retrievers/vector/), traversing the [HNSW](https://arxiv.org/abs/1603.09320) index using cosine similarity.
2. **Live Database Execution**:
   - For item listings and status checks (e.g., *"what tickets are assigned to me in PROJ?"*), the query engine translates the request into platform-native queries (such as JQL with disjunctive multi-field expansion) and fetches live records.
3. **Hybrid Context Fusion**:
   - When querying issue trackers, Ragdoll enriches live API results with pre-indexed vector search results (`source_filter="jira"`). It deduplicates records by issue key (`PROJ-1234`) and injects both real-time ticket metadata and relevant historical discussion into the LLM context.
4. **Planned Roadmap (Sparse BM25 + Reciprocal Rank Fusion)**:
   - For direct keyword matching against arbitrary code identifiers (e.g., `calculate_metric`) without live APIs, a future release is planned to integrate an inverted [Okapi BM25](https://en.wikipedia.org/wiki/Okapi_BM25) index and merge dense and lexical scores using [Reciprocal Rank Fusion (RRF)](https://dl.acm.org/doi/10.1145/1571941.1572114) (Cormack et al., SIGIR 2009).

### 4. Generation & Context Delimitation

Retrieved chunks are formatted as context and injected into the LLM prompt. To prevent indirect prompt injection from untrusted external text, Ragdoll isolates retrieved passages inside explicit delimiter blocks and structures metadata concisely:

```text
--- CONTEXT ---
[jira:PROJ-1234] (source: jira | key: PROJ-1234 | status: Open | project: PROJ)
Detailed ticket description and resolution steps...

[code:src/service/worker.py::process_batch] (source: code | file_path: src/service/worker.py)
def process_batch(items: list[Item]) -> Result:
    ...
--- END CONTEXT ---
```

The engine supports three generation modes:

- **Search** — returns raw scored chunks and source metadata without generative synthesis.
- **Summarize** — single-turn generation with an extractive/summarization prompt.
- **Chat** — multi-turn conversation with accumulated dialogue context and cited sources.

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

## Hybrid RAG vs. Direct Platform MCP

A core architectural motivation for Ragdoll is solving the **Platform Capacity Exhaustion** problem that occurs when autonomous developer agents use direct [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) integrations against team collaboration infrastructure (such as enterprise Jira, Confluence, or Bitbucket instances).

When agents issue broad exploratory queries over live platform APIs, they trigger heavy backend load: unbounded database joins, search index scans, network latency spikes, and context window bloat caused by full page XHTML markup.

Ragdoll establishes a **decoupled operational model** based on the 95/5 rule:

| **Dimension** | **Offline Local RAG (Ragdoll)** | **Direct Live Platform MCP** |
| :--- | :--- | :--- |
| **Primary Role** | Broad technical knowledge retrieval & historical context | Targeted, single-entity live actions & status updates |
| **Typical Inquiries** | *"How do we handle worker retry strategies?"* | *"Fetch current status of PROJ-1234"* or *"Create bug ticket"* |
| **Platform Impact** | **Near-zero runtime load** on live Jira/Bitbucket servers (queries hit indexed store) | Direct query on live database; risks connection pool exhaustion |
| **Query Latency** | Sub-second (**< 50 ms**) | Network-bound (**500 ms – 3 s**) |
| **Data Freshness** | Bound to ETL sync schedule (e.g., hourly/nightly) | Real-time (immediate live state) |
| **Token Efficiency** | High: returns 2–3 precise semantic chunks | Low: often dumps raw full-page markup/JSON into context |
| **[IPI Mitigation](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)** | Sanitized and stripped during ingestion | Requires live runtime prompt escaping |

By directing 95% of developer read queries to Ragdoll's local or centralized ChromaDB index, teams protect internal server stability while ensuring sub-second response times for AI coding assistants.

---

## Local vs. Cloud Model Selection

When architecting a RAG workflow, engineering teams must evaluate the distinct operational roles of **embedding models** versus **generation LLMs**:

1. **Embedding Models (Vector Indexing)**:
   - For document indexing, **local open-weight models are strongly recommended**. Models such as [`nomic-embed-text`](https://arxiv.org/abs/2402.01613) or [`BGE-M3`](https://arxiv.org/abs/2402.03216) run efficiently on standard CPUs or single small GPUs, incur no external per-token API costs, and help keep bulk internal wikis, codebases, and ticket databases within the institutional network during ingestion.

2. **Generation Models (Chat & Coding Synthesis)**:
   - The choice of generation LLM depends on organizational privacy policies and available GPU hardware:

| Dimension | Cloud-Hosted LLMs (Claude, GPT, Gemini) | Local Open-Weight LLMs (Qwen-Coder, Llama) |
| :--- | :--- | :--- |
| **Reasoning & Code Quality** | Frontier-grade reasoning and expansive context windows | Highly capable; requires 32B+ parameters for complex multi-file logic |
| **Data Privacy** | Egress to cloud provider; mitigated contractually under **Enterprise Licenses** (no-training terms, zero data retention) | High on-premises control; data and inference stay on local infrastructure |
| **Hardware Overhead** | Zero local GPU requirements; accessible from thin clients | Requires dedicated GPU memory (24 GB–80 GB VRAM) |
| **Operating Cost** | Pay-per-token API subscription costs | Upfront hardware investment; zero per-query fees |

### Privacy Boundary with Cloud-Hosted Coding Agents

When connecting cloud-based AI tools (e.g., Claude Code, Cursor, Copilot) to Ragdoll via MCP (`ragdoll mcp`), the bulk database remains local. Only the specific top-K retrieved passages (typically 2–3 chunks totaling < 2 KB) are transmitted to the cloud provider's API as tool results.

#### Enterprise Licensing Safeguards

For organizations leveraging commercial coding assistants alongside Ragdoll, an **Enterprise License** (such as [Anthropic Commercial Terms](https://www.anthropic.com/legal/commercial-terms), [OpenAI Enterprise Privacy](https://openai.com/enterprise-privacy/), [GitHub Copilot Trust Center](https://resources.github.com/copilot-trust-center/), or [Google Cloud Vertex AI Data Governance](https://cloud.google.com/vertex-ai/docs/general/data-governance)) establishes vital contractual and operational safeguards:

- **No Model Training Commitment**: Providers contractually guarantee that customer prompts, retrieved context chunks, and generated completions are never used to train or refine public or proprietary foundation models.
- **Zero or Bounded Data Retention (ZDR)**: Inputs and outputs are processed ephemerally or retained only for minimal, auditable compliance windows (such as [Zero Data Retention](https://platform.openai.com/docs/models#how-we-use-your-data) or 30-day encrypted abuse monitoring with enterprise opt-out capabilities).
- **Enterprise Compliance & Encryption**: Enforces TLS 1.3 in transit and AES-256 at rest, audited under [SOC 2 Type II](https://www.aicpa-cima.com/resources/landing/system-and-organization-controls-soc-suite-of-services), [ISO/IEC 27001](https://www.iso.org/standard/27001), and organizational Data Processing Agreements (DPAs).

This architecture provides a complementary, defense-in-depth model: **Ragdoll enforces technical data minimization** locally (sharing only the precise top-$k$ snippets needed to answer the question rather than whole repositories), while **Enterprise Licensing provides legal and boundary isolation** in the cloud. For organizations handling classified, ITAR, or strictly air-gapped data, running both Ragdoll and Ollama fully on-premises remains the most conservative operating posture.

---

## Security, Privacy & Ingestion Boundaries

1. **Role-Based Space Curation**:
   - Ragdoll ingestion scripts should explicitly scope JQL queries and repository targets to public and team-level development spaces, excluding HR, private drafts, or personal user spaces.
2. **Context Delimiter Framing**:
   - Chunks injected into agent context are wrapped inside structured delimiter blocks (e.g., `--- CONTEXT ---` or boundary tags) to neutralize [indirect prompt injection (IPI)](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) attempts (see [Greshake et al., 2023](https://arxiv.org/abs/2302.12173)) embedded in issue comments or user documentation.
3. **Local Embedding Execution**:
   - Text vectorization executes on internal infrastructure, helping keep proprietary algorithms, internal business logic, and sensitive project details within institutional boundaries during indexing.

---

## Quality Evaluation & Benchmark Metrics

To maintain index fidelity over time, Ragdoll pipelines can be evaluated using standard quantitative benchmarks:

1. **Hit Rate @ k**: The proportion of test queries where the authoritative reference chunk appears in the top k retrieved results.
2. **[Mean Reciprocal Rank (MRR)](https://en.wikipedia.org/wiki/Mean_reciprocal_rank)**: Measures the positional quality of the primary reference chunk in the returned list.
3. **Generation Faithfulness**: Using automated evaluation frameworks (such as [Ragas](https://docs.ragas.io/) or [TruLens](https://www.trulens.org/)) to verify that generated answers cite and faithfully reflect the retrieved context chunks, reducing hallucinations.
4. **Freshness Tracking**: Monitoring the delta between source modification timestamps and ChromaDB update watermarks to detect stale documentation.

---

## Local Storage Layout

```
~/.ragdoll/
├── config.toml       # User-level configuration (chmod 600)
├── chat_history      # Readline history for chat (last 500 queries)
└── data/
    └── chroma/       # ChromaDB persistent storage
```
