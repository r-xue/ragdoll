# 🧶 Ragdoll

**Retrieval-Augmented Generation Driven by Offline Local LLMs**

A fully-local RAG system that ingests JIRA tickets, PDF documents, and Python
source code, indexes them for semantic search, and connects to a local LLM via
[Ollama](https://ollama.ai) for interactive Q&A, summarization, and chat.

> **Privacy-first:** All data stays on your machine — nothing is sent to external services by default.

> [!NOTE]
> Ragdoll is an independent open-source project created and maintained in a personal capacity. It is not an official work project and does not represent the official positions, software roadmaps, or endorsement of any employer or institution.

## Key Features

- **Multi-source ingestion** — PDF, JIRA, Bitbucket, GitHub, Git, and Python code (AST-parsed)
- **Semantic search** — ChromaDB vector store with cosine similarity
- **Local LLM** — Ollama-powered embedding and generation
- **Interactive chat** — Multi-turn RAG chat with persistent history
- **MCP Server** — First-class support for the Model Context Protocol (stdio & sse). *(Note: If you connect a cloud-based AI client to this MCP server, the search results it retrieves will be sent to that external AI provider).*
- **Privacy-first** — Everything runs locally; no external API calls
- **Flexible configuration** — 4-layer precedence (env → project → user → defaults)

## Prerequisites

- **Python 3.12+**
- **[Ollama](https://ollama.ai)** running locally with:
  - An embedding model (e.g. `nomic-embed-text`)
  - A chat model (e.g. `gpt-oss:20b`, `deepseek-r1:32b`)
- **[pixi](https://pixi.sh)** for environment management

## Quick Start

```bash
# Clone and enter the project
cd ragdoll

# Install with pixi (creates isolated env + editable install)
pixi install

# Set up user-level configuration
mkdir -p ~/.ragdoll && chmod 700 ~/.ragdoll
cat > ~/.ragdoll/config.toml << 'EOF'
jira_url = "https://your-jira.example.com"
jira_user = "your.user"
jira_token = "YOUR_PAT_TOKEN"
jira_auth_method = "pat"  # "pat" for JIRA Data Center, "basic" for Cloud

bitbucket_url = "https://your-bitbucket.example.com"
bitbucket_user = "your.user"
bitbucket_token = "YOUR_HTTP_ACCESS_TOKEN"
bitbucket_auth_method = "pat"

github_token = "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN"
EOF
chmod 600 ~/.ragdoll/config.toml

# Check everything is connected
pixi run ragdoll status
```

## Usage

### Ingest Data

```bash
# Ingest PDF files or directories
pixi run ragdoll ingest pdf ./docs/technical_handbook.pdf
pixi run ragdoll ingest pdf ./reports/

# Ingest JIRA issues via JQL
pixi run ragdoll ingest jira --jql "project = CORE AND updated >= -30d"
pixi run ragdoll ingest jira --jql "project = AUTH AND updated >= -60d" --max-results 100

# Ingest from a different JIRA instance (multi-site)
pixi run ragdoll ingest jira \
  --url https://other-jira.example.com \
  --token OTHER_PAT \
  --jql "project = EXT AND updated >= -30d"

# Ingest Bitbucket Pull Requests and comments
pixi run ragdoll ingest bitbucket --project PROJ --repo backend --state ALL

# Ingest GitHub Issues and PR discussions
pixi run ragdoll ingest github myorg myrepo --state all

# Ingest Python source code (AST-parsed per function/class)
pixi run ragdoll ingest code ./src/
pixi run ragdoll ingest code ./path/to/project/
```

#### Reingesting Data (LlamaIndex Update)
If you are upgrading from an older version of `ragdoll` to the LlamaIndex-backed version, your existing ChromaDB data is fully backward compatible. However, it is highly recommended to wipe the old index and reingest your data to take advantage of LlamaIndex's superior semantic chunking (which splits by sentences instead of fixed character limits).

To clear your database and start fresh:
```bash
# Delete the old ChromaDB collection
rm -rf ~/.ragdoll/data/chroma

# Re-run your ingestion commands
pixi run ragdoll ingest jira --jql "project = CORE AND updated >= -30d"
pixi run ragdoll ingest pdf ./docs/
```

### Search

```bash
# Semantic search across all ingested data
pixi run ragdoll search "database query performance regression"
pixi run ragdoll search "connection pool lazy initialization" --source jira
pixi run ragdoll search "data processing pipeline" --source pdf -n 5
pixi run ragdoll search "embedding function" --source code
```

### Summarize

```bash
# Summarize a topic from ingested data
pixi run ragdoll summarize "What are the known issues with the connection pool?"
pixi run ragdoll summarize "batch worker parallelization" --source jira
```

### Interactive Chat

```bash
# Start an interactive RAG chat session
pixi run ragdoll chat
pixi run ragdoll chat --source jira  # only use JIRA context
pixi run ragdoll chat --source code  # only use source code context
```

Chat features:
- **Persistent history** — arrow-up recalls previous questions across sessions
  (stored in `~/.ragdoll/chat_history`)
- **Line editing** — full readline support (backspace, arrows, Home/End)
- **Multi-turn** — context accumulates within a session

## Configuration

Ragdoll uses a **4-layer precedence** configuration strategy:

| Priority | Source | Purpose |
|----------|--------|---------|
| 1 (highest) | `RAGDOLL_*` environment variables | CI/ephemeral overrides |
| 2a | `./ragdoll.toml` in the project directory | Project-level settings |
| 2b | `./.env` in the project directory | Project-level secrets |
| 3 | `~/.ragdoll/config.toml` | User-level defaults & credentials |
| 4 (lowest) | Package defaults | Hardcoded fallbacks |

### Settings Reference

| Variable / TOML key | Default | Description |
|---------------------|---------|-------------|
| `jira_url` | — | JIRA server URL |
| `jira_user` | — | JIRA username |
| `jira_token` | — | JIRA API token or PAT |
| `jira_auth_method` | `pat` | `"pat"` for Data Center, `"basic"` for Cloud |
| `jira_batch_size` | `50` | Issues per API request |
| `ollama_host` | `http://localhost:11434` | Ollama API endpoint |
| `embed_model` | `nomic-embed-text` | Embedding model |
| `chat_model` | `gpt-oss:20b` | Chat / generation model |
| `temperature` | `0.3` | LLM sampling temperature |
| `data_dir` | `~/.ragdoll/data` | ChromaDB storage directory |
| `collection_name` | `ragdoll` | ChromaDB collection name |
| `chunk_size` | `1000` | Characters per chunk |
| `chunk_overlap` | `200` | Overlap between consecutive chunks |
| `top_k` | `20` | Default retrieval count |

## Architecture

```
Source Data                Pipeline                        Storage
───────────                ────────                        ───────
PDF files     ─┐
JIRA tickets  ─┼─→  Ingestor  →  Chunker  →  Embedder  →  ChromaDB
Python code   ─┘              (AST-aware)   (Ollama)       (local)
                                                             ↑
Query Flow                                                   │
──────────                                                   │
CLI / Chat  →  Embed query  →  Retriever  ←──────────────────┘
                                 ↓
                           LLM (Ollama)  →  Streamed answer
```

### Data Sources

| Source | Module | Strategy |
|--------|--------|----------|
| **PDF** | `ragdoll.ingest.pdf` | PyMuPDF text extraction → recursive character splitter |
| **JIRA** | `ragdoll.ingest.jira` | REST API with JQL → structured text per issue |
| **Bitbucket** | `ragdoll.ingest.bitbucket` | REST API → structured text per PR and comment thread |
| **GitHub** | `ragdoll.ingest.github` | REST API → structured text per Issue/PR and comment thread |
| **Git** | `ragdoll.ingest.git` | Commit history extraction across all branches |
| **Code** | `ragdoll.ingest.code` | AST parsing → one Document per function/class/module docstring |

### Key Components

- **Config** (`ragdoll.config`) — Pydantic Settings with 4-layer precedence
- **Chunker** (`ragdoll.ingest.chunker`) — Recursive character text splitter
- **Embedder** (`ragdoll.llm.ollama`) — Ollama HTTP client for embeddings and generation
- **Vector Store** (`ragdoll.store.vectordb`) — ChromaDB with cosine similarity
- **Retriever** (`ragdoll.query.retriever`) — Semantic search with source filtering
- **RAG Chain** (`ragdoll.query.rag`) — Context-augmented generation and chat
- **CLI** (`ragdoll.cli`) — Click-based interface with Rich formatting

## Documentation

Full documentation is hosted at **[ragdoll.readthedocs.io](https://ragdoll.readthedocs.io/)**.

You can also build the documentation locally from the `docs/` directory using Sphinx:

```bash
pixi run docs
```

## AI Assistance & Transparency Disclosure

Ragdoll is developed using AI pair-programming and agentic workflows alongside human engineers.

- **Human Oversight & Responsibility**: The codebase, architectural designs, and operational policies are reviewed, edited, and validated by human maintainers. Human contributors retain full responsibility for the accuracy, security, and licensing integrity of all code in this repository.
- **Rigorous Verification**: All code changes, refactors, and features must pass comprehensive offline test suites (`pixi run test`), linting, and documentation builds before merging.
- **Strict Privacy & Secret Hygiene**: Development strictly adheres to zero-egress policies—no proprietary tokens, internal credentials, or confidential datasets are ever exposed during AI-assisted workflows. Architectural invariants and agent safety rules are codified in [`AGENTS.md`](./AGENTS.md).

## Independent Community Project & Personal Capacity Disclaimer

This repository is an independent open-source software project:

- **Personal Effort**: All contributions, code, documentation, and architectural designs represent the independent, voluntary efforts of individual contributors acting strictly in their personal capacities.
- **Outside Official Working Hours**: Work on this project is conducted entirely during personal, off-duty time.
- **Not Work-for-Hire**: Contributions are not commissioned, assigned, supervised, or endorsed by any current, past, or future employers of the contributors.
- **No Institutional Affiliation**: Opinions, designs, and implementations expressed herein are solely those of the individual authors and do not reflect the official positions, policies, or technical roadmaps of any employer or institution.

## License

MIT
