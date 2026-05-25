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
pixi run ragdoll ingest jira --jql "project = MAIN" --max-results 200
```

### Multi-Site Ingestion

To ingest from **multiple JIRA instances** (e.g., an internal Data Center and
a partner's Cloud instance), you can define named server blocks in your 
`~/.ragdoll/config.toml`:

```toml
[jira_servers.primary]
url = "https://primary-jira.example.com"
user = "your.username"
token = "YOUR_PERSONAL_ACCESS_TOKEN"
auth_method = "pat"

[jira_servers.cloud]
url = "https://company.atlassian.net"
user = "you@company.com"
token = "CLOUD_API_TOKEN"
auth_method = "basic"
```

Then use the `--server` flag to ingest from a specific configured site:

```bash
# Primary site (uses global defaults if --server is omitted)
pixi run ragdoll ingest jira --jql "project = MAIN AND updated >= -30d"

# Secondary Data Center site
pixi run ragdoll ingest jira --server primary --jql "project = EXT AND updated >= -30d"

# Cloud site with basic auth
pixi run ragdoll ingest jira --server cloud --jql "project = CLOUD"
```

Alternatively, you can manually override settings per-invocation using CLI flags:

| Override Flag | Description |
|---------------|-------------|
| `--server` | Name of the pre-configured server in config.toml |
| `--url` | JIRA server URL |
| `--user` | Username (for basic auth) |
| `--token` | API token or PAT |
| `--auth-method` | `"pat"` or `"basic"` |

All issues from all sites are stored in the same vector collection, so
queries, summaries, and chat draw from all ingested sources.

### Extracted Metadata

Every ingested JIRA ticket carries the following metadata fields, available
for both auto-retrieval filtering and context display.

**From JiraReader (built-in):**

| Metadata Key | Type | Description |
|---|---|---|
| `id` | `str` | Internal JIRA issue ID |
| `title` | `str` | Issue summary |
| `url` | `str` | Permalink to the issue |
| `created_at` | `str` | Creation timestamp |
| `updated_at` | `str` | Last update timestamp |
| `labels` | `str` | Comma-separated labels |
| `status` | `str` | Workflow status (Open, In Progress, Closed, etc.) |
| `assignee` | `str` | Assignee display name |
| `reporter` | `str` | Reporter display name |
| `project` | `str` | Project name |
| `issue_type` | `str` | Bug, Story, Task, Epic, etc. |
| `priority` | `str` | Critical, Major, Minor, Trivial, etc. |
| `epic_key` | `str` | Parent epic issue key |
| `epic_summary` | `str` | Parent epic summary |
| `epic_description` | `str` | Parent epic description |

**Enriched from raw JIRA API:**

| Metadata Key | Type | Description |
|---|---|---|
| `key` | `str` | Issue key (e.g. `PIPE-1234`) |
| `components` | `str` | Comma-separated component names (e.g. `hif_makeimages, hif_findcont`) |
| `fix_versions` | `str` | Target fix version names |
| `affects_versions` | `str` | Affected version names |
| `resolution` | `str` | Resolution status (Fixed, Won't Fix, Duplicate, etc.) |
| `resolution_date` | `str` | When the issue was resolved |
| `subtask_count` | `int` | Number of subtasks |
| `linked_issues` | `str` | Related issues with relationship (e.g. `blocks PRJ-999, is blocked by PRJ-123`) |
| `votes` | `int` | Vote count |
| `watches` | `int` | Watcher count |
| `sprint` | `str` | Sprint name (Jira Software agile boards) |
| `story_points` | `float` | Story points estimate |
| `environment` | `str` | Environment field text |

> **Note:** `components`, `fix_versions`, `affects_versions`, and
> `linked_issues` are also appended to the document text so they are
> discoverable via semantic search, not just metadata filtering.

## Bitbucket Pull Requests

**Module:** `ragdoll.ingest.bitbucket`

Fetches pull requests and their activity threads from an on-premise Bitbucket Server (Data Center) via the REST API. Each PR is converted into a structured document containing:

- PR Title, description, and status
- Author information
- A chronological thread of all comments, approvals, and merges

### Example

```bash
# Ingest all PRs (Open, Merged, and Declined) from a specific repo
pixi run ragdoll ingest bitbucket --project PROJ --repo backend --state ALL

# Ingest only Open PRs
pixi run ragdoll ingest bitbucket --project PROJ --repo backend --state OPEN
```

### Multi-Site Ingestion

Like JIRA, you can configure multiple Bitbucket instances in `~/.ragdoll/config.toml`:

```toml
[bitbucket_servers.internal]
url = "https://bitbucket.example.com"
user = "your.username"
token = "YOUR_HTTP_ACCESS_TOKEN"
auth_method = "pat"
```

Then specify the server during ingestion:

```bash
pixi run ragdoll ingest bitbucket --server internal --project PROJ --repo backend
```

### Extracted Metadata

| Metadata Key | Type | Description |
|---|---|---|
| `repo` | `str` | Bitbucket repository slug |
| `pr_id` | `str` | Pull Request numerical ID |
| `author` | `str` | Author of the PR |
| `title` | `str` | PR Title |
| `status` | `str` | MERGED, OPEN, or DECLINED |
| `created_at_ts` | `float` | Unix timestamp of creation |
| `updated_at_ts` | `float` | Unix timestamp of last update |


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
