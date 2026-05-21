# Usage

## Ingesting Data

Ragdoll supports three data sources. Each ingestion pipeline extracts text,
chunks it, computes embeddings via Ollama, and stores them in ChromaDB.

### PDF Documents

```bash
# Single file
pixi run ragdoll ingest pdf ./handbook.pdf

# Directory (recursive)
pixi run ragdoll ingest pdf ./docs/

# Multiple paths
pixi run ragdoll ingest pdf ./report.pdf ./specs/
```

PDFs are processed with PyMuPDF and split into overlapping character-based chunks.

### JIRA Tickets

```bash
# Recent tickets from a project
pixi run ragdoll ingest jira --jql "project = MAIN AND updated >= -30d"

# Specific component with a limit
pixi run ragdoll ingest jira --jql "project = MAIN AND component = frontend" --max-results 100

# Multiple projects
pixi run ragdoll ingest jira --jql "project in (MAIN, OTHER) AND updated >= -60d"
```

JIRA ingestion extracts the full issue structure: summary, description,
comments, status, components, labels, and fix versions.

```{note}
JIRA Data Center uses Personal Access Tokens (PATs) with Bearer auth
(`jira_auth_method = "pat"`). JIRA Cloud uses basic auth with API tokens
(`jira_auth_method = "basic"`).
```

### Multi-Site JIRA Ingestion

To ingest from **multiple JIRA instances**, use `--url`, `--token`, and
`--auth-method` flags to override the configured defaults per invocation:

```bash
# Site 1 — uses defaults from ~/.ragdoll/config.toml
pixi run ragdoll ingest jira --jql "project = MAIN AND updated >= -30d"

# Site 2 — different JIRA Data Center instance
pixi run ragdoll ingest jira \
  --url https://other-jira.example.com \
  --token OTHER_PAT_TOKEN \
  --jql "project = EXT AND updated >= -30d"

# Site 3 — JIRA Cloud with basic auth
pixi run ragdoll ingest jira \
  --url https://mycompany.atlassian.net \
  --user me@company.com \
  --token CLOUD_API_TOKEN \
  --auth-method basic \
  --jql "project = CLOUD"
```

All ingested issues go into the same ChromaDB collection, so you can
search and chat across all sites together.

| Flag | Purpose |
|------|---------|
| `--url` | JIRA server URL (overrides config) |
| `--user` | JIRA username (overrides config) |
| `--token` | API token / PAT (overrides config) |
| `--auth-method` | `pat` or `basic` (overrides config) |

### Python Source Code

```bash
# Ingest a source tree
pixi run ragdoll ingest code ./src/

# Single file
pixi run ragdoll ingest code ./src/ragdoll/config.py
```

Code ingestion uses Python's `ast` module to parse source files into
semantically meaningful units:

- **Functions** — each top-level `def` / `async def` becomes a document
- **Classes** — each `class` (including all methods) becomes a document
- **Module docstrings** — extracted as separate documents

This preserves code boundaries rather than blindly splitting text, giving the
LLM coherent context to reason about.

Directories like `__pycache__`, `.git`, `.venv`, and `.pixi` are
automatically skipped.

### Chunking Options

All ingest commands accept `--chunk-size` and `--chunk-overlap` to override
the defaults (1000 chars / 200 chars overlap):

```bash
pixi run ragdoll ingest pdf ./docs/ --chunk-size 500 --chunk-overlap 100
```

## Searching

```bash
# Basic semantic search
pixi run ragdoll search "tclean performance regression"

# Filter by source
pixi run ragdoll search "embedding function" --source code
pixi run ragdoll search "calibration pipeline" --source pdf

# Control result count
pixi run ragdoll search "bandpass flagging" -n 5
```

Results are displayed in a table with source ID, similarity score, and text preview.

## Summarizing

```bash
pixi run ragdoll summarize "What are the known issues with imaging?"
pixi run ragdoll summarize "tclean parallelization" --source jira
```

Summarization retrieves relevant chunks, injects them as context, and asks the
LLM to produce a structured summary with source citations.

## Interactive Chat

```bash
pixi run ragdoll chat
pixi run ragdoll chat --source jira
pixi run ragdoll chat --source code -n 12
```

### Chat Features

- **Multi-turn context** — conversation history accumulates within a session
- **Persistent history** — arrow-up/down recalls previous questions across
  sessions (stored in `~/.ragdoll/chat_history`, capped at 500 entries)
- **Full line editing** — backspace, arrow keys, Home/End all work
- **Source filtering** — `--source` limits retrieval to a specific data source
- **Streaming** — responses are streamed token-by-token

### Chat Commands

| Input | Action |
|-------|--------|
| `quit` / `exit` / `q` | End the session |
| `Ctrl+C` | End the session |
| Arrow up/down | Recall previous questions |

## Status

```bash
pixi run ragdoll status
```

Shows current configuration, vector store statistics, and available Ollama models.
