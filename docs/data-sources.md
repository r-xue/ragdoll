# Data Sources

Ragdoll supports five data source types, each with a specialised ingestion
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

```{note}
**Scope:** This module *only* ingests Pull Request metadata and discussions. It does **not** clone or ingest the repository's source code files. To ingest actual codebase files, use the `ragdoll ingest code` command (see [Python Source Code](#python-source-code)).
```

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


## GitHub Issues & Pull Requests

**Module:** `ragdoll.ingest.github`

Fetches issues, pull requests, and discussion threads from public or private GitHub repositories (including GitHub Enterprise Server) via the GitHub REST API. Each issue or PR is converted into a structured document containing:

- Issue / PR Title, number, status (`open` or `closed`), and type label (`Issue` or `PR`)
- Author login name
- Creation date and full issue description
- A chronological thread of all comments and activity

```{note}
**Scope:** This module ingests Issue and Pull Request discussions, descriptions, and comments. To ingest the repository's actual Python source code files, use `ragdoll ingest code` after cloning the repository.
```

### Example

```bash
# Ingest all Issues and PRs (both Open and Closed) with full comment threads
pixi run ragdoll ingest github myorg myrepo --state all

# Ingest only Open issues & PRs
pixi run ragdoll ingest github myorg myrepo --state open

# Pass a token directly via CLI to avoid API rate limits
pixi run ragdoll ingest github myorg myrepo --token "ghp_..."
```

### Multi-Site / Enterprise Ingestion

You can configure global or enterprise GitHub instances in `~/.ragdoll/config.toml`:

```toml
# Default / Public GitHub
github_token = "ghp_YOUR_PERSONAL_ACCESS_TOKEN"

# GitHub Enterprise Server
[github_servers.enterprise]
url = "https://github.internal.mycompany.com/api/v3"
token = "ghp_ENTERPRISE_TOKEN"
```

Then specify the server during ingestion:

```bash
pixi run ragdoll ingest github --server enterprise --owner myorg --repo internal-service --state all
```

### Extracted Metadata

| Metadata Key | Type | Description |
|---|---|---|
| `source` | `str` | `"github"` |
| `owner` | `str` | GitHub organization or username |
| `repo` | `str` | GitHub repository name |
| `issue_number` | `str` | Issue or Pull Request number |
| `is_pr` | `bool` | `True` if Pull Request, `False` if standard Issue |
| `author` | `str` | Author's GitHub username |
| `title` | `str` | Issue / PR title |
| `status` | `str` | Workflow status (`open` or `closed`) |
| `created_at_ts` | `float` | Unix timestamp of creation |
| `updated_at_ts` | `float` | Unix timestamp of last update |


## Python Source Code

**Module:** `ragdoll.ingest.code`

Uses Python's built-in `ast` module to parse source files into semantically
meaningful units rather than blind text splitting. 

When you use a traditional text chunker, it slices a document by character count, which frequently cuts loops, conditionals, and functions in half. By parsing the **Abstract Syntax Tree (AST)** instead, Ragdoll ensures that the LLM is given complete, unbroken functions and classes. This preserves the semantic context of the code.

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

## Git Repository History

**Module:** `ragdoll.ingest.git`

Parses a local git repository to ingest commit history across all branches and tags. This allows the LLM to understand when features were introduced, why code was changed, and how different branches relate to one another.

### Extraction Strategy

Using standard git CLI commands, it extracts each commit into a `Document` containing:
- Commit Hash and Parent Hashes
- Branch and Tag References (e.g., `HEAD -> main`, `origin/feature-branch`)
- Author Name and Date
- Commit Subject and Body

```{tip}
Because it uses `--all`, it automatically covers the entire repository graph, regardless of which branch is currently checked out on your filesystem.
```

### Extracted Metadata

| Metadata Key | Type | Description |
|---|---|---|
| `repo_path` | `str` | Absolute path to the local repository |
| `commit_hash` | `str` | SHA-1 commit hash |
| `parents` | `str` | Space-separated parent hashes |
| `refs` | `str` | Associated branch/tag references |
| `author` | `str` | Author's name |
| `subject` | `str` | Commit subject line |
| `created_at_ts` | `float` | Unix timestamp of the commit |

### Example

```bash
# Ingest the last 1000 commits from a local repo
pixi run ragdoll ingest git /path/to/local/repo

# Ingest up to 5000 commits
pixi run ragdoll ingest git /path/to/local/repo --max-commits 5000
```

## Source Filtering

All query commands support `--source` to filter retrieved chunks:

```bash
pixi run ragdoll search "tclean" --source jira
pixi run ragdoll summarize "calibration" --source pdf
pixi run ragdoll chat --source code
pixi run ragdoll search "bugfix" --source git
pixi run ragdoll search "feature request" --source github
```

This filters on the `source` metadata field in ChromaDB, which is set to
`"pdf"`, `"jira"`, `"bitbucket"`, `"github"`, `"code"`, or `"git"` during ingestion.
