# Local Knowledge Staging & Batch Ingestion

Ragdoll provides a structured **local staging area** (`sources/`) for dropping local documents and cloning repositories prior to indexing. This allows you to organize knowledge assets by type, keep sensitive data private on your local disk, and run automated batch ingestion workflows with helper scripts.

```{note}
All files placed inside `sources/pdf/`, `sources/markdown/`, and `sources/repos/` (as well as custom subdirectories) are **excluded from version control** via `.gitignore`. They remain strictly on your local workstation.
```

---

## Staging Directory Layout

```
sources/
├── pdf/              # PDF documents (memos, reports, manuals, architecture specs)
├── markdown/         # Markdown documentation, technical notes, and API contracts
├── repos/            # Cloned Git repositories for code and commit history analysis
├── code/             # Standalone code files, samples, and snippets (optional)
├── github/           # GitHub export files or configuration dumps (optional)
├── bitbucket/        # Bitbucket export files or configuration dumps (optional)
└── jira/             # Jira ticket exports or saved search dumps (optional)
```

* **`sources/pdf/`**: Place PDF technical memos, reports, architecture specifications, or user manuals here.
* **`sources/markdown/`**: Place Markdown specifications, technical notes, or API contracts here.
* **`sources/repos/`**: Clone external source code repositories here for deep code semantics and Git commit history ingestion.
* **`sources/code/`**: Place standalone code files and snippets without full version control history.
* **`sources/github/`, `sources/bitbucket/`, `sources/jira/`**: Store exported dumps, tickets, or source configurations when working with API data exports offline.

---

## Quickstart: Staged Ingestion

### Step 1: Stage Your Sources

1. **PDFs**: Copy `.pdf` files into `sources/pdf/`
2. **Markdown**: Copy `.md` files into `sources/markdown/`
3. **Repositories**: Add Git repository URLs to `sources/manifests/repos.txt` (format: `<repo_url> [branch] [custom_folder_name]`):
   ```text
   https://github.com/my-org/core-engine.git main core-engine
   https://github.com/my-org/web-ui.git
   ```
   Then run the repository staging command:
   ```bash
   pixi run ragdoll stage-repos
   ```
   *(Alternatively, manually clone repositories directly into `sources/repos/<repo-name>`)*

### Step 2: Ingest into Vector Store

Run the built-in all-in-one ingestion command:
```bash
# Ingest all staged sources (with incremental change detection)
pixi run ragdoll ingest-all

# Sync repositories from manifests/repos.txt first and ingest:
pixi run ragdoll ingest-all --clone

# Force re-indexing of all sources even if unmodified:
pixi run ragdoll ingest-all --force
```

This command automatically scans:
1. `sources/pdf/` and ingests all `.pdf` documents using `ragdoll ingest pdf`.
2. `sources/markdown/` and ingests all `.md` technical notes using `ragdoll ingest code`.
3. `sources/repos/` and performs dual ingestion on all cloned repositories (ingesting AST-parsed code structures via `ragdoll ingest code` and Git commit histories via `ragdoll ingest git`).
4. `sources/manifests/` and queries declared Jira issues, GitHub repos, and Bitbucket PRs.

### Step 3: Start Chatting

Launch the interactive local RAG terminal:
```bash
pixi run ragdoll chat
```

---

## Data Source Types & Ingestion Details

Ragdoll supports both local file ingestion and direct API collection.

### 1. PDF Documents (`sources/pdf/`)
PDF documents are parsed locally using PyMuPDF.
* **Extraction:**
  - Full-text content extracted per page
  - Document metadata (title, author, creation date)
  - Structured sections based on document layout
* **CLI Command:**
  ```bash
  pixi run ragdoll ingest pdf sources/pdf/
  # or single file:
  pixi run ragdoll ingest pdf sources/pdf/technical_memo.pdf
  ```

---

### 2. Markdown Specifications (`sources/markdown/`)
Markdown files are ingested as code and technical documentation chunks.
* **Extraction:**
  - Headers, sections, tables, and prose
  - Embedded code blocks and technical contracts
* **CLI Command:**
  ```bash
  pixi run ragdoll ingest code sources/markdown/
  ```

---

### 3. Git Repositories (`sources/repos/` or `sources/git/`)
Full Git repositories are cloned and analyzed locally for version control context.
* **Extraction:**
  - Commit history, commit messages, and diff rationale
  - Author and committer metadata
  - Branch information and temporal changes over time
* **CLI Command:**
  ```bash
  pixi run ragdoll ingest git sources/repos/<repo-name>
  ```
* **Use When:** You want to query *why* changes were made, track commit patterns, understand repository evolution, or perform authorship queries.

---

### 4. Standalone Code & Snippets (`sources/code/`)
Individual code files or directory trees parsed at the AST level without git metadata.
* **Extraction:**
  - AST-parsed functions, classes, methods, and modules
  - Inline comments, type signatures, and docstrings
  - Code syntax and semantic structure
* **CLI Command:**
  ```bash
  pixi run ragdoll ingest code sources/code/
  # or across a cloned repo:
  pixi run ragdoll ingest code sources/repos/<repo-name>
  ```
* **Use When:** You want to index current codebase syntax and semantic structures without needing commit history.

---

### 5. GitHub API (`sources/github/`)
Data collected directly via the GitHub REST API or loaded from offline exports.
* **Configuration:**
  Configure your personal access token in `~/.ragdoll/config.toml` or via environment variables:
  ```bash
  export GITHUB_TOKEN="<your-github-token>"
  ```
* **Extraction:**
  - Repository structure and files
  - Issue discussions and pull requests
  - Commit histories and PR review comments
* **CLI Command:**
  ```bash
  pixi run ragdoll ingest github <owner> <repo> --state all
  ```

---

### 6. Bitbucket Server / Cloud (`sources/bitbucket/`)
Data collected directly via the Bitbucket REST API.
* **Configuration:**
  Configure credentials in `~/.ragdoll/config.toml` or environment variables:
  ```bash
  export BITBUCKET_URL="https://your-bitbucket.example.com"
  export BITBUCKET_USER="<username>"
  export BITBUCKET_TOKEN="<http-access-token-or-password>"
  ```
* **Extraction:**
  - Pull requests, diffs, and review comments
  - Commit history and repository contents
* **CLI Command:**
  ```bash
  pixi run ragdoll ingest bitbucket --project <PROJECT_KEY> --repo <repo-slug> --state ALL
  ```

---

### 7. Jira Issue Tracker (`sources/jira/`)
Issues and tickets collected via Jira REST API using JQL queries.
* **Configuration:**
  Configure credentials in `~/.ragdoll/config.toml` or environment variables:
  ```bash
  export JIRA_URL="https://your-jira.example.com"
  export JIRA_USERNAME="<username>"
  export JIRA_API_TOKEN="<pat-or-api-token>"
  ```
* **Extraction:**
  - Issues, tasks, bugs, and epics
  - Issue changelogs, status transitions, and resolution details
  - Comments and attachment metadata
* **CLI Command:**
  ```bash
  pixi run ragdoll ingest jira --jql "project = PROJ AND updated >= -30d" --max-results 100
  ```

---

## Deep Dive: `git` vs. `code` Ingestion

When indexing source code, you can ingest using the `git` ingester, the `code` ingester, or **both**:

| Aspect | Git (`ingest git`) | Code (`ingest code`) |
| :--- | :--- | :--- |
| **Source** | Full repositories containing `.git/` history | Source files, scripts, or directories |
| **Context Extracted** | Commit history, author metadata, diffs, timestamps | AST nodes, functions, classes, docstrings, semantics |
| **Primary Use Case** | Understand repo evolution, commit rationales, bug fixes | Index current implementations, API signatures, functions |
| **Storage Requirement** | Cloned repositories (with `.git` folder) | Standalone source files or directories |
| **Can They Overlap?** | **Yes** — Ingesting a repository with `code` indexes its current syntax, and `git` indexes its commit history |

```{tip}
**Dual Ingestion (Recommended):**
Running both `ragdoll ingest code <repo>` and `ragdoll ingest git <repo>` gives the LLM complete visibility — it can explain how a function works today (via `code`) and why it was modified in a recent commit (via `git`). The `pixi run ragdoll ingest-all` script does this automatically for all repositories in `sources/repos/`.
```

---

## General Ingestion Workflow & Best Practices

1. **Prepare Data**:
   - Collect documents or clone repos into the appropriate `sources/` subdirectory.
   - Organize subdirectories cleanly (e.g. `sources/pdf/memos/`, `sources/repos/my-org/repo1/`).

2. **Configure Credentials Safely**:
   - Store API tokens in `~/.ragdoll/config.toml` (secured with `chmod 600`) or pass via environment variables (`.env`).
   - **Never** commit API tokens or credentials to Git repositories.

3. **Incremental Ingestion & Re-indexing**:
   - Re-running ingestion commands will update the vector database with new and modified items.
   - If switching chunking strategies or rebuilding the database from scratch, clear the vector store (`rm -rf ~/.ragdoll/data/chroma`) and re-run `pixi run ragdoll ingest-all`.

4. **Performance for Large Repositories**:
   - For very large repositories or archives with tens of thousands of commits/files, ingest in batches or filter by recent updates (e.g., using `--jql "updated >= -30d"` for Jira).

