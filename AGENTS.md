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

### 4.1 Secret & Credential Hygiene
- **Never hardcode secrets**: Do not place API keys, personal access tokens (PATs), passwords, session cookies, or user credentials into code, docstrings, tests, commits, or logs.
- **Configuration Precedence**: Respect the 4-layer resolution strategy in `src/ragdoll/config.py`:
  1. `RAGDOLL_*` environment variables (highest priority)
  2. `./ragdoll.toml` (project settings) and `./.env` (project secrets)
  3. `~/.ragdoll/config.toml` (user defaults and credentials)
  4. Package defaults in `config.py` (lowest priority)
- **Git Ignore**: Never commit `.env`, `.env.*`, `ragdoll.toml`, or `~/.ragdoll/config.toml`. Ensure these files remain in `.gitignore`.
- **Output Masking**: Always mask tokens and sensitive headers in CLI output, logs, or error traces (e.g. `jira_token: "********"`).

### 4.2 Privacy Boundary & Zero-Egress Principle
- **Offline by Default**: Ragdoll is designed as an on-premises / local-first tool. Do not add code that transmits raw document chunks, codebases, or internal tickets to external cloud endpoints.
- **Local Embedding Invariant**: Embeddings must be generated locally (e.g., via local Ollama models like `nomic-embed-text`) so sensitive knowledge does not leave the machine during ingestion.
- **MCP Server Minimization**: When running the MCP server (`pixi run ragdoll mcp`), only return the top-$k$ relevant chunks requested by the query. Never expose endpoints that dump the entire vector store or export raw database files.

### 4.3 ChromaDB Integrity & Concurrency Safety
- **Interrupt Protection**: ChromaDB's underlying Rust HNSW index can suffer file corruption or segmentation faults if interrupted mid-write. Always wrap batch write operations with `GracefulInterrupt` (`from ragdoll.store.safety import GracefulInterrupt`) to defer `SIGINT` until the active write finishes.
- **Database Health**: Use `check_chromadb_health()` before performing vector operations.
- **No Unsolicited Database Deletion**: NEVER run destructive operations (`rm -rf ~/.ragdoll/data/chroma`, `ragdoll clear --force`, or dropping collections) without explicit human confirmation.

### 4.4 Prompt Injection Mitigation (IPI)
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
- **Error Handling**: Fail gracefully with actionable error messages and hints (using `rich.console` or Click exceptions) rather than raw unhandled stack traces.
