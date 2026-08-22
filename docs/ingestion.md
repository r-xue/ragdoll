# Ingesting Data

Ragdoll supports multiple data sources (PDF, JIRA, Bitbucket, GitHub, Git, and Python code). Each ingestion pipeline extracts text,
chunks it, computes embeddings via Ollama, and stores them in ChromaDB.

## PDF Documents

```bash
# Single file
pixi run ragdoll ingest pdf ./handbook.pdf

# Directory (recursive)
pixi run ragdoll ingest pdf ./docs/

# Multiple paths
pixi run ragdoll ingest pdf ./report.pdf ./specs/
```

PDFs are processed with PyMuPDF and split into overlapping character-based chunks.

## JIRA Tickets

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

### Incremental Ingestion & Change Detection

Ragdoll automatically tracks issue modification timestamps (`updated_at_ts`) in ChromaDB. On repeated runs:
- **Unchanged issues** are automatically skipped, eliminating redundant Ollama embedding compute.
- **New or modified issues** are embedded and upserted into the vector store.

To force re-embedding of all matching tickets regardless of timestamps, pass `-f` / `--force`:

```bash
# Force full re-indexing of all matching tickets
pixi run ragdoll ingest jira --server primary --jql "project = MAIN" --force
```

```{note}
JIRA Data Center uses Personal Access Tokens (PATs) with Bearer auth
(`jira_auth_method = "pat"`). JIRA Cloud uses basic auth with API tokens
(`jira_auth_method = "basic"`).
```

## Multi-Site JIRA Ingestion

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

## GitHub Issues & Pull Requests

```bash
# Ingest all open and closed issues & PRs (with all comments)
pixi run ragdoll ingest github myorg myrepo --state all

# Ingest only open issues/PRs
pixi run ragdoll ingest github myorg myrepo --state open

# Pass an API token to prevent rate limiting
pixi run ragdoll ingest github myorg myrepo --token YOUR_GITHUB_PAT
```

GitHub ingestion extracts the full discussion context: issue title, description,
author, state (open/closed), creation date, and chronological comment threads.

## Python Source Code

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

## Chunking Options

All ingest commands accept `--chunk-size` and `--chunk-overlap` to override
the defaults (1000 chars / 200 chars overlap):

```bash
pixi run ragdoll ingest pdf ./docs/ --chunk-size 500 --chunk-overlap 100
```


## Verbose Progress & Debugging

For large ingestion tasks (such as thousands of Jira issues or commit histories), pass `-v` or `--verbose` right after `ragdoll` to view live batch progress and debug logging:

```bash
# Ingest with live batch-by-batch progress
pixi run ragdoll -v ingest jira --server primary --jql "project = MAIN"
```
