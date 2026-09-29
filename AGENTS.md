# AGENTS.md — Ragdoll

> Development guidelines, architectural invariants, and safety rules for AI agents and human contributors working on **Ragdoll**.

---

## 1. Project Overview & Objective

**Ragdoll** is a privacy-first, fully-local Retrieval-Augmented Generation (RAG) system:

- **Offline & Private**: Indexes JIRA tickets, Confluence spaces, Git repositories, Bitbucket/GitHub PRs, PDF documents, and Python source code (AST-parsed) entirely on the local machine without leaking proprietary data to external cloud APIs.
- **Core Technology Stack**: Python 3.12+, [pixi](https://pixi.sh) environment management, ChromaDB (Rust HNSW backend), LlamaIndex, Ollama (local embeddings & LLM chat), FastAPI / FastMCP, Click, and Rich.
- **Model Context Protocol (MCP)**: Exposes local semantic retrieval to AI coding agents via stdio/SSE while enforcing data minimization boundaries.

---

## 2. Environment & Tooling: Pixi is Recommended for Development & Testing

**`pixi` is strongly recommended for all development, testing, and execution in Ragdoll.**

- **Reproducible & Isolated**: Manages the complete Python 3.12 runtime and native C/Rust toolchains required by ChromaDB's HNSW index, SQLite, and PyMuPDF without system pollution.
- **Editable Development**: Automatically installs `ragdoll-ai` in editable mode (`pixi install`), ensuring local code changes take effect immediately across all CLI tasks and test runs.
- **Consistent Testing**: Binds `pytest` and coverage configurations directly to the locked environment (`pixi.lock`), eliminating "works on my machine" inconsistencies.
- **Rule**: Avoid using bare system `python`, `pip`, `venv`, or `conda`. Always prefix commands with `pixi run`.

### Setup

```bash
pixi install                  # Installs locked dependencies and editable ragdoll-ai
```

### Common Commands

- **Run CLI**: `pixi run ragdoll <command>` (e.g., `pixi run ragdoll status`)
- **Interactive Chat**: `pixi run chat` (or `pixi run ragdoll chat`)
- **Semantic Search**: `pixi run search "<query>"`
- **Start MCP Server**: `pixi run ragdoll mcp`
- **Run Ingestion**:

  ```bash
  pixi run ragdoll ingest pdf <path/to/doc.pdf>
  pixi run ragdoll ingest code <path/to/src/>
  pixi run ragdoll ingest git <path/to/repo>
  pixi run ragdoll ingest jira --jql "<query>"
  pixi run ragdoll ingest confluence --space "<SPACE>"
  pixi run ragdoll ingest bitbucket --project <PROJ> --repo <REPO>
  pixi run ragdoll ingest github <owner> <repo>
  pixi run ragdoll ingest all <path/to/sources/>
  ```

- **Local Staging**:

  ```bash
  pixi run ragdoll stage-repos       # Clone or update repos from sources/manifests/repos.txt
  pixi run ragdoll stage-pdfs        # Verify staged PDF documents
  ```

- **Run Tests**: `pixi run test` (executes `pytest`)
- **Test Coverage**: `pixi run test-cov` (executes `pytest --cov=ragdoll tests/`)
- **Build Docs**: `pixi run docs` (`sphinx-build -b html docs docs/_build/html`)

Always run `pixi run test` to verify that all unit tests pass before completing any changes.

---

## 3. Repository Architecture & Layout

```
ragdoll/
├── pyproject.toml              # Project dependencies, pixi configuration, pytest settings
├── pixi.lock                   # Lockfile for reproducible multi-platform dependencies
├── AGENTS.md                   # This instruction file
├── README.md                   # User quickstart and overview
├── .env.example                # Example environment variables (committed)
├── src/ragdoll/
│   ├── config.py               # Pydantic-settings 4-layer configuration precedence
│   ├── cli.py                  # Click CLI entrypoint and command handlers
│   ├── mcp.py                  # Model Context Protocol (FastMCP) server
│   ├── api.py                  # FastAPI endpoints
│   ├── ui.py                   # Rich terminal / Gradio web UI
│   ├── store/
│   │   ├── vectordb.py         # ChromaDB client & vector store abstraction
│   │   └── safety.py           # Database integrity (GracefulInterrupt, health checks)
│   ├── query/
│   │   ├── retriever.py        # Dense + lexical hybrid search, Reciprocal Rank Fusion (RRF)
│   │   └── rag.py              # Context assembly, prompt formatting, LLM synthesis
│   ├── ingest/
│   │   ├── pdf.py              # PyMuPDF document extraction & chunking
│   │   ├── code.py             # AST-based Python code chunking by function/class
│   │   ├── git.py              # Local Git commit & diff parser
│   │   ├── jira.py             # Jira issue & changelog ingestion
│   │   ├── confluence.py       # Confluence space & XHTML page parser
│   │   ├── bitbucket.py        # Bitbucket Server / Cloud PR & comment ingestion
│   │   ├── github.py           # GitHub PR & issue discussion ingestion
│   │   └── staging.py          # Local multi-source file manifest scanner
│   └── llm/
│       └── ollama.py           # Ollama client for embeddings and generation
├── tests/                      # Offline pytest test suite (mocking external APIs)
└── docs/                       # Sphinx documentation (architecture, configuration, guides)
```

---

## 4. Safety & Security Rules (CRITICAL)

### 4.1 Prohibited Secret Access & Shell Commands (CRITICAL)

- **Strictly Prohibited Files**: AI agents must NEVER inspect, read, or output the contents of:
  - `~/.ragdoll/config.toml` (contains user PAT tokens and credentials)
  - `./.env`, `./.env.*`, or `./ragdoll.toml` (project secrets and local overrides)
  - `~/.ragdoll/chat_history` (may contain prior user queries and sensitive search snippets)
  - `~/.ragdoll/data/` or any ChromaDB/SQLite storage files
- **Strictly Prohibited Commands**: AI agents must NEVER execute commands that dump environment variables, shell states, or credentials, including:
  - `env`, `printenv`, `export -p`, `set`
  - `cat /proc/*/environ`
  - Inspecting `.git/config` with embedded remote credentials
- **Never Hardcode Secrets**: Do not place API keys, personal access tokens (PATs), passwords, session cookies, or user credentials into code, docstrings, tests, commits, or logs.
- **Pydantic SecretStr Masking**: In `src/ragdoll/config.py`, all credentials (`jira_token`, `bitbucket_token`, `github_token`, `confluence_token`, `confluence_cookie`, `chroma_auth_token`) use `MaskedSecret` (`pydantic.SecretStr`) to ensure tokens are automatically masked as `**********` in `repr()`, `str()`, and logs.
- **Configuration Precedence**: Respect the 4-layer resolution strategy in `src/ragdoll/config.py`:
  1. `RAGDOLL_*` environment variables (highest priority)
  2. `./ragdoll.toml` (project settings) and `./.env` (project secrets)
  3. `~/.ragdoll/config.toml` (user defaults and credentials)
  4. Package defaults in `config.py` (lowest priority)
- **Git Ignore**: Never commit `.env`, `.env.*`, `ragdoll.toml`, or `~/.ragdoll/config.toml`. Ensure these files remain in `.gitignore`.
- **Output Masking**: Always mask tokens and sensitive headers in CLI output, logs, or error traces (e.g. `jira_token: "********"`).

### 4.2 Synthetic Data Invariant & Privacy Boundary (Zero Real-Data Egress)

- **Mandatory Synthetic Generics**: All agent-generated artifacts—including test fixtures, mock datasets, CLI examples, docstrings, documentation, and prompt templates—MUST exclusively use synthetic, generic placeholders. AI agents must NEVER generate or leak proprietary schemas, internal ticket keys, organizational domain names, or real employee/user identities.
  - **Issue / Ticket Keys**: Exclusively use canonical generic abbreviations: `PROJ-101`, `APP-202`, `SVC-303`, `TASK-404`, `DEMO-505`, or `TEST-123`. Never emit real or organizational ticket key prefixes.
  - **Schemas & Data Models**: Use universal application domains (e.g., e-commerce, generic telemetry, web analytics, task queues: `users`, `orders`, `events`, `metrics`, `items`, `status_history`). Never mirror proprietary, internal, or domain-specific database schemas or business entities.
  - **Identities & PII**: Use standard documentation personas (`Alice`, `Bob`, `Charlie`, `Dana`) and RFC 2606 reserved email addresses (`user@example.com`, `dev@example.org`). Never synthesize real personal names, usernames, or internal employee identifiers.
  - **Domains, Hostnames & Network Addresses**: Use RFC 2606 / RFC 6761 reserved top-level and second-level domains (`https://jira.example.com`, `https://git.example.com`, `https://example.org`) or RFC 5737 documentation IP ranges (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`). Never use real internal organizational hostnames, VPN endpoints, or intranets.
  - **Code Identifiers & Algorithms**: Use standard computing and software engineering patterns (e.g., `process_batch()`, `worker_retry_policy()`, `token_bucket()`, `connection_pool()`). Never replicate proprietary algorithm naming, internal heuristics, or organization-specific operational terms.
- **Zero Environment Reflection Invariant**: AI agents must NEVER inspect or reflect contextual identifiers found in local workspace paths (e.g., directory paths containing corporate/departmental names), git remote URLs, local user accounts, or commit logs into code or documentation. Always sanitize to clean generic equivalents before emitting.
- **No Live Ingestion During Agent Sessions**:
  - AI agents must NEVER execute live network ingestion commands (`ragdoll ingest jira`, `ragdoll ingest bitbucket`, `ragdoll ingest confluence`) against production servers.
  - Development and testing must rely 100% on offline unit tests (`pixi run test`) with synthetic mocked HTTP adapters.

### 4.3 Privacy Boundary & Zero-Egress Principle

- **Offline by Default**: Ragdoll is designed as an on-premises / local-first tool. Do not add code that transmits raw document chunks, codebases, or internal tickets to external cloud endpoints.
- **Local Embedding Invariant**: Embeddings must be generated locally (e.g., via local Ollama models like `nomic-embed-text`) so sensitive knowledge does not leave the machine during ingestion.
- **MCP Server Minimization**: When running the MCP server (`pixi run ragdoll mcp`), only return the top-$k$ relevant chunks requested by the query. Never expose endpoints that dump the entire vector store or export raw database files.

### 4.4 ChromaDB Integrity & Concurrency Safety

- **Interrupt Protection**: ChromaDB's underlying Rust HNSW index can suffer file corruption or segmentation faults if interrupted mid-write. Always wrap batch write operations with `GracefulInterrupt` (`from ragdoll.store.safety import GracefulInterrupt`) to defer `SIGINT` until the active write finishes.
- **Database Health**: Use `check_chromadb_health()` before performing vector operations.
- **No Unsolicited Database Deletion**: NEVER run destructive operations (`rm -rf ~/.ragdoll/data/chroma`, `ragdoll clear --force`, or dropping collections) without explicit human confirmation.

### 4.5 Prompt Injection Mitigation (IPI)

- Ingested external texts (Jira tickets, PR comments, user PDFs, scraped documentation) are untrusted inputs that may contain indirect prompt injections.
- Always isolate retrieved context inside explicit delimiting structures (e.g., `<retrieved_context source="...">...</retrieved_context>`) when assembling prompts for generation.
- Sanitize and validate file paths during ingestion to prevent directory traversal vulnerabilities.

---

## 5. Git & Review Policy

- **Do NOT automatically stage, commit, or push**: Never run `git add`, `git commit`, or `git push` autonomously. Always leave all new and modified files unstaged in the working directory, waiting for explicit human review, staging, and confirmation.
- **Verify first**: Always run `pixi run test` (and `pixi run docs` if documentation was touched) and confirm all checks pass before presenting completed changes.
- **No destructive file operations**: Never execute `rm -rf`, file deletions, or branch resets without explicit confirmation.
- **No history rewrites**: Never run `git push --force` or rewrite repository history.

---

## 6. Coding & Testing Standards

- **Python Version**: Target Python 3.12+. Use modern type annotations (`from __future__ import annotations`, `X | Y` union syntax, Pydantic `BaseModel` / `BaseSettings`).
- **Offline Tests**: All unit tests in `tests/` must be 100% offline. Mock network requests (`httpx`, `jira`, `atlassian`, `ollama`) and use pytest's `tmp_path` fixture for ChromaDB storage.
- **Backward Compatibility**: Preserve ChromaDB metadata schemas and ingestion formats so existing collections do not become unreadable upon upgrade.
- **Diagrams & Visualizations**: When documentation requires diagrams, flowcharts, or architecture visualizations, use **Mermaid** (` ```mermaid ` blocks). Sphinx is configured with `sphinxcontrib.mermaid` to render them natively.
- **Error Handling**: Fail gracefully with actionable error messages and hints (using `rich.console` or Click exceptions) rather than raw unhandled stack traces.
