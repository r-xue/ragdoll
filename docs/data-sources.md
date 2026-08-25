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

### Pagination & Incremental Ingestion

Issues are fetched in batches (default: 100 per request) with automatic
pagination. Use `--max-results` to cap the total:

```bash
pixi run ragdoll ingest jira --jql "project = MAIN" --max-results 200
```

Ragdoll automatically compares incoming issue `updated` timestamps against existing ChromaDB metadata. If an issue has not changed since its last ingestion, Ragdoll skips embedding it, saving CPU/GPU resources. Use `-f` / `--force` to bypass this check:

```bash
pixi run ragdoll ingest jira --server primary --jql "project = MAIN" --force
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
| `key` | `str` | Issue key (e.g. `PROJ-1234`) |
| `components` | `str` | Comma-separated component names (e.g. `auth, backend, worker`) |
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
**Scope:** This module *only* ingests Pull Request metadata and discussions. It does **not** clone or ingest the repository's source code files. To ingest actual codebase files, use the `ragdoll ingest code` command (see [Source Code](#source-code-multi-language)).
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
pixi run ragdoll ingest github --server enterprise myorg internal-service --state all
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


## Source Code (Multi-Language)

**Module:** `ragdoll.ingest.code`

Ingests source code repositories and directories across multiple programming languages, templates, markup files, and build configurations.

Rather than blindly splitting source files by arbitrary character counts, Ragdoll applies language-aware extraction techniques to preserve structural boundaries (classes, functions, subroutines, modules). This ensures the LLM receives complete, coherent code blocks rather than fragmented snippets.

### Complete List of Supported Languages & Formats

| Category | Language / Format | Extensions / Special Filenames | Extraction Strategy |
|---|---|---|---|
| **Python** | Python | `.py` | **AST Parser**: Extracts discrete `def`, `async def`, `class` (with all methods), and module-level docstrings with exact line numbers. |
| **C / C++ & GPU** | C, C++, CUDA | `.cpp`, `.cc`, `.cxx`, `.c`, `.hpp`, `.hh`, `.hxx`, `.h`, `.tcc`, `.cu`, `.cuh` | **Semantic Block Parser**: Extracts `class`, `struct`, namespace, and function implementations, preserving header and signature context. |
| **Fortran** | Fortran 77 / 90 / 95 | `.f`, `.for`, `.f90`, `.f95` | **Routine Scanner**: Detects and extracts `subroutine`, `function`, `module`, and `program` blocks along with parameter declarations. |
| **Shell & Scripting** | Bash, POSIX Shell, Zsh | `.sh`, `.bash`, `.zsh` | Chunks script logic with file path headers and line number annotations. |
| **Templates & Markup** | XML Tasks & Recipes, Mako Web Templates | `.xml`, `.mako` | Structured chunking preserving XML data/task definitions, workflow procedures, and Mako HTML templates. |
| **Build & Tooling** | CMake, Make, Docker | `CMakeLists.txt`, `.cmake`, `Makefile`, `Dockerfile` | Target-aware chunking preserving build targets, flags, and recipe rules. |
| **Modern Systems** | Rust, Go | `.rs`, `.go` | Context-aware code chunking with syntax metadata. |
| **Web & Frontend** | JavaScript, TypeScript | `.js`, `.jsx`, `.ts`, `.tsx` | Syntax-aware component and script chunking. |
| **Database & Config** | SQL, TOML, YAML, JSON | `.sql`, `.toml`, `.yaml`, `.yml`, `.json` | Query and structured configuration chunking. |
| **LaTeX & Science** | LaTeX, BibTeX | `.tex`, `.latex`, `.sty`, `.cls`, `.bib` | **Document Chunking**: Ingests research papers, scientific formulas, macros, and bibliography citations. |
| **Documentation & Specs** | Markdown, reStructuredText, Plain Text | `.md`, `.markdown`, `.rst`, `.txt` | **Section & Text Chunking**: Ingests technical notes, RFCs, architecture specs, and design documents. |

### Small File Handling & Context Headers

- **Small Files (<= 30 lines or <= chunk_size)**: Kept intact as a single Document (`node_type = "file"`) to prevent unnecessary fragmentation.
- **Large Files**: Sliced into semantic blocks or coherent overlapping chunks (`node_type = "chunk"` or `"function"`/`"class"`).
- **Context Injection**: Every extracted chunk is prefixed with a comment header (e.g. `// File: src/engine.cpp (class: Engine, lines 40-120)`) so the LLM always knows the origin file path and exact line range for citations.

### Extracted Metadata

| Metadata Key | Type | Description |
|---|---|---|
| `source` | `str` | `"code"` |
| `filepath` | `str` | Relative or absolute path to the source file |
| `language` | `str` | Normalized language identifier (e.g. `python`, `cpp`, `fortran`, `xml`, `shell`) |
| `node_type` | `str` | Node type (`function`, `class`, `struct`, `subroutine`, `module_doc`, `file`, `chunk`) |
| `name` | `str` | Name of the function, class, subroutine, or file |
| `lineno` | `int` | Starting line number in the source file |
| `end_lineno` | `int` | Ending line number in the source file |
| `file_hash` | `str` | SHA-256 hash of file contents for incremental delta caching |
| `mtime_ts` | `float` | File modification epoch timestamp |

### Automatic Ignore Rules

During directory traversal, the following directories and binary file extensions are automatically skipped:

* **Ignored Directories**: `__pycache__`, `.git`, `.pixi`, `.tox`, `.venv`, `venv`, `node_modules`, `build`, `dist`, `.mypy_cache`, `.pytest_cache`, `*.egg-info`
* **Ignored Artifacts**: `.o`, `.so`, `.a`, `.dylib`, `.dll`, `.exe`, `.class`, `.pyc`, `.pyo`, `.tar`, `.gz`, `.zip`, `.bin`, `.dat`, `.png`, `.jpg`, `.pdf`

### CLI Usage & Extension Filtering

```bash
# Ingest all supported source files across a repository (incremental by default)
pixi run ragdoll ingest code /path/to/repo

# Ingest specific source directories
pixi run ragdoll ingest code ./src/ ./include/ ./recipes/

# Filter by specific extensions (e.g. only C++ and Python)
pixi run ragdoll ingest code /path/to/repo --ext cpp,cc,h,hpp,py

# Force re-indexing of all source files even if unmodified
pixi run ragdoll ingest code /path/to/repo --force

# Ingest specific XML task recipes and Mako templates
pixi run ragdoll ingest code ./templates/recipes/ --ext xml,mako

# Customize chunk sizing for non-AST source files
pixi run ragdoll ingest code ./src/ --chunk-size 1200 --chunk-overlap 150
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

### Incremental Ingestion & Change Detection

Ragdoll assigns a deterministic ID to each commit based on its SHA-1 hash (`git-{repo_name}-{commit_hash}`). On repeated invocations:
- **Existing commits** already in ChromaDB are skipped in milliseconds, eliminating redundant Ollama embedding compute.
- **New commits** added since the last run are embedded and upserted.
- Use `-f` / `--force` to force re-indexing of all matching commits.

### Extracted Metadata

| Metadata Key | Type | Description |
|---|---|---|
| `source` | `str` | `"git"` |
| `repo_name` | `str` | Repository folder name |
| `repo_path` | `str` | Absolute path to the local repository |
| `commit_hash` | `str` | SHA-1 commit hash |
| `parents` | `str` | Space-separated parent hashes |
| `refs` | `str` | Associated branch/tag references |
| `author` | `str` | Author's name |
| `subject` | `str` | Commit subject line |
| `created_at_ts` | `float` | Unix timestamp of the commit |

### Example

```bash
# Ingest the 2,000 most recent commits across all branches (default)
pixi run ragdoll ingest git /path/to/local/repo

# Ingest full repository history (all commits from root to HEAD)
pixi run ragdoll ingest git /path/to/local/repo --all

# Or pass 0 for unlimited commits
pixi run ragdoll ingest git /path/to/local/repo --max-commits 0

# Exclude merge commits for high-signal direct changes
pixi run ragdoll ingest git /path/to/local/repo --no-merges

# Force re-indexing of all matching commits
pixi run ragdoll ingest git /path/to/local/repo --force
```

## Source Filtering

All query commands support `--source` to filter retrieved chunks:

```bash
pixi run ragdoll search "memory allocation" --source jira
pixi run ragdoll summarize "database migration" --source pdf
pixi run ragdoll chat --source code
pixi run ragdoll search "bugfix" --source git
pixi run ragdoll search "feature request" --source github
```

This filters on the `source` metadata field in ChromaDB, which is set to
`"pdf"`, `"jira"`, `"bitbucket"`, `"github"`, `"code"`, or `"git"` during ingestion.
