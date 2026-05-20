# Data Sources

Ragdoll supports three data source types, each with a specialised ingestion
strategy designed to preserve semantic meaning.

## PDF Documents

**Module:** `ragdoll.ingest.pdf`

Uses [PyMuPDF](https://pymupdf.readthedocs.io/) to extract text content from
PDF files. Each page produces a `Document` with metadata including the source
file path and page number.

### Supported Inputs

- Single PDF files
- Directories (recursively finds all `*.pdf` files)

### Example

```bash
pixi run ragdoll ingest pdf ./technical_handbook.pdf
pixi run ragdoll ingest pdf ./documentation/
```

## JIRA Tickets

**Module:** `ragdoll.ingest.jira`

Fetches issues from a JIRA instance (Data Center or Cloud) via the REST API.
Each issue is converted into a structured text document containing:

- Issue key, summary, status, type, and priority
- Assignee, reporter, created/updated dates
- Components, labels, and fix versions
- Full description text
- All comments with authors and timestamps

### Authentication

| JIRA Type | Auth Method | Config |
|-----------|-------------|--------|
| Data Center | PAT (Bearer token) | `jira_auth_method = "pat"` |
| Cloud | Basic auth (user + API token) | `jira_auth_method = "basic"` |

### Pagination

Issues are fetched in batches (default: 50 per request) with automatic
pagination. Use `--max-results` to cap the total:

```bash
pixi run ragdoll ingest jira --jql "project = CAS" --max-results 200
```

### Multi-Site Ingestion

To ingest from **multiple JIRA instances** (e.g., an internal Data Center and
a partner's Cloud instance), use CLI flags to override connection settings
per invocation:

```bash
# Primary site (uses ~/.ragdoll/config.toml defaults)
pixi run ragdoll ingest jira --jql "project = CAS AND updated >= -30d"

# Secondary Data Center site
pixi run ragdoll ingest jira \
  --url https://other-jira.example.com \
  --token OTHER_PAT_TOKEN \
  --jql "project = EXT AND updated >= -30d"

# Cloud site with basic auth
pixi run ragdoll ingest jira \
  --url https://company.atlassian.net \
  --user you@company.com \
  --token CLOUD_API_TOKEN \
  --auth-method basic \
  --jql "project = CLOUD"
```

| Override Flag | Description |
|---------------|-------------|
| `--url` | JIRA server URL |
| `--user` | Username (for basic auth) |
| `--token` | API token or PAT |
| `--auth-method` | `"pat"` or `"basic"` |

All issues from all sites are stored in the same vector collection, so
queries, summaries, and chat draw from all ingested sources.

## Python Source Code

**Module:** `ragdoll.ingest.code`

Uses Python's built-in `ast` module to parse source files into semantically
meaningful units rather than blind text splitting.

### Extraction Strategy

| AST Node | Document Type | Content |
|----------|--------------|---------|
| `FunctionDef` / `AsyncFunctionDef` | `function` | Full function source with file path header |
| `ClassDef` | `class` | Full class source (including all methods) |
| Module docstring | `module_doc` | Module-level docstring with file path |
| Syntax error | `raw` | Entire file as raw text (fallback) |

### Metadata

Each code document includes rich metadata:

```python
{
    "source": "code",
    "filepath": "src/ragdoll/config.py",
    "node_type": "class",       # function, class, module_doc, raw
    "name": "Settings",
    "lineno": 42,
    "end_lineno": 127,
}
```

### Ignored Directories

The following directories are automatically skipped during recursive walks:

- `__pycache__`, `.git`, `.pixi`, `.tox`
- `.venv`, `venv`, `node_modules`
- `*.egg-info`, `.eggs`

### Example

```bash
# Ingest a full project
pixi run ragdoll ingest code ./src/

# Ingest a single module
pixi run ragdoll ingest code ./src/ragdoll/query/rag.py
```

## Source Filtering

All query commands support `--source` to filter retrieved chunks:

```bash
pixi run ragdoll search "tclean" --source jira
pixi run ragdoll summarize "calibration" --source pdf
pixi run ragdoll chat --source code
```

This filters on the `source` metadata field in ChromaDB, which is set to
`"pdf"`, `"jira"`, or `"code"` during ingestion.
