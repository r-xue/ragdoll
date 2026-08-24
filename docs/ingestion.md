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

## Bitbucket Server (Data Center) Pull Requests

```bash
# Ingest all PRs (Open, Merged, and Declined) from a project repository
pixi run ragdoll ingest bitbucket --server primary --project PROJ --repo backend --state ALL

# Ingest only open PRs
pixi run ragdoll ingest bitbucket --server primary --project PROJ --repo backend --state OPEN
```

Bitbucket ingestion extracts PR titles, descriptions, author information, status, and full chronological discussion and review activity threads.

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

## Source Code (Multi-Language)

```bash
# Ingest all supported source files in a repository
pixi run ragdoll ingest code /path/to/repo

# Ingest specific files or folders
pixi run ragdoll ingest code ./src/ ./include/

# Ingest only specific file types (e.g. C++ and Python)
pixi run ragdoll ingest code /path/to/repo --ext py,cpp,h,xml

# Ingest LaTeX papers, style files, and bibliography (.tex, .sty, .bib)
pixi run ragdoll ingest code /path/to/latex_docs

# Ingest Markdown design specifications & documentation
pixi run ragdoll ingest code sources/markdown
```

Ragdoll supports 30+ source code and markup file types (Python, C/C++, CUDA, Fortran, Shell, XML, Mako, CMake, Rust, Go, TypeScript, etc.). Code files are parsed using language-aware extractors (AST, semantic block parsing, routine boundary scanners) to keep functions, classes, and subroutines intact.

Build directories (`__pycache__`, `.git`, `.venv`, `.pixi`, `build`, `dist`) and compiled binaries (`.o`, `.so`, `.a`, `.pyc`) are automatically skipped.

```{seealso}
For the full matrix of all supported file extensions, parsing mechanisms, and metadata schemas, see **[Data Sources: Source Code](data-sources.md#source-code-multi-language)**.
```

## Git Repository History

```bash
# Ingest the 2,000 most recent commits across all branches (default)
pixi run ragdoll ingest git /path/to/local/repo

# Ingest full repository history (all commits from initial root to HEAD)
pixi run ragdoll ingest git /path/to/local/repo --all

# Or specify custom limit (0 for unlimited full history)
pixi run ragdoll ingest git /path/to/local/repo --max-commits 5000

# Exclude merge commits for high-signal direct code changes
pixi run ragdoll ingest git /path/to/local/repo --no-merges

# Force re-indexing of all matching commits
pixi run ragdoll ingest git /path/to/local/repo --force
```

Git ingestion extracts commit hashes, parents, branch/tag references, authors, dates, subject lines, and commit bodies across the entire repository graph. Ragdoll tracks commit hashes in ChromaDB and automatically skips already-indexed commits on subsequent runs.

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
