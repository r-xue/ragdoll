# Knowledge Sources & Staging Area (`sources/`)

This directory serves as the **local staging ground** and declarative specification area for documents, codebases, and external API queries indexed into Ragdoll.

> [!NOTE]
> All document contents placed inside `pdf/`, `markdown/`, and `repos/` (as well as custom subdirectories) are **excluded from Git** via `.gitignore`. They remain safely and privately on your local workstation. Only declarative manifests (`manifests/`) are version-controlled.

---

## Directory Layout

```text
sources/
 pdf/                      # Local PDF whitepapers, memos, and manuals (.gitignored)
   ├── memos/                # Technical memos, algorithmic whitepapers, scientific notes
   ├── architecture/         # System architecture documents, design specifications, RFCs
   └── user_guides/          # Operations manuals, installation guides, user documentation
 markdown/                 # Local Markdown specs and design notes (.gitignored)
   ├── specs/                # Markdown design documents, data schemas, interface contracts
   └── notes/                # Research notes, technical meeting summaries, scratchpads
 repos/                    # Local Git repository checkouts (.gitignored)
 manifests/                # Declarative API, PDF & Repository Manifests (version-controlled)
    ├── repos.txt             # Git repositories to clone (AST code + Git history)
    ├── pdf.txt               # Public PDF download URLs to sync into pdf/
    ├── jira.txt              # Jira JQL queries to fetch tickets & comments
    ├── github.txt            # GitHub repositories to fetch Issues & PR discussions
    └── bitbucket.txt         # Bitbucket repositories to fetch PR reviews & discussions
```

---

## Quickstart: Staging & Ingestion

Ingestion is executed directly via the `ragdoll` CLI.

### 1. Stage Listed Repositories & PDFs (Optional Prep)
To clone or pull repositories and download declared PDFs into their staging folders:

```bash
# Clone or update external Git repositories declared in manifests/repos.txt:
pixi run ragdoll stage-repos

# Download remote PDF documents declared in manifests/pdf.txt into pdf/:
pixi run ragdoll stage-pdfs
```

### 2. One-Click Multi-Source Ingestion
Ingest all PDF memos, Markdown specifications, staged codebases, and manifest queries in one command:

```bash
# Ingest all knowledge into your local vector database:
pixi run ragdoll ingest-all

# Automatically stage/pull repositories, download PDFs, and index everything:
pixi run ragdoll ingest-all --clone

# Or push directly to a Central Team ChromaDB Server:
RAGDOLL_CHROMA_HOST=http://ragdoll-server.internal:8000 pixi run ragdoll ingest-all
```

---

## Contribution Guidelines

### 1. Document Contributions (PDF & Markdown)
* Place PDFs in `sources/pdf/memos/`, `sources/pdf/architecture/`, or `sources/pdf/user_guides/`.
* Place Markdown files in `sources/markdown/specs/` or `sources/markdown/notes/`.
* Use clear, descriptive, lowercase filenames with underscores (e.g. `memo_101_calibration_heuristics.pdf`).

### 2. Declarative Manifests (`sources/manifests/`)
* **Code Repositories**: Declare Git clone URLs in [`sources/manifests/repos.txt`](./manifests/repos.txt).
* **PDF Documents**: Declare public download URLs in [`sources/manifests/pdf.txt`](./manifests/pdf.txt).
* **Jira Tickets**: Declare JQL queries in [`sources/manifests/jira.txt`](./manifests/jira.txt).
* **GitHub Discussions**: Declare repos in [`sources/manifests/github.txt`](./manifests/github.txt).
* **Bitbucket PRs**: Declare repos in [`sources/manifests/bitbucket.txt`](./manifests/bitbucket.txt).

---

## Querying Ingested Content

Once ingested, the entire knowledge base is immediately accessible via Ragdoll:

```bash
# Interactive Chat
pixi run ragdoll chat

# Semantic Search
pixi run ragdoll search "memory allocation buffer" --source code
pixi run ragdoll search "calibration pipeline" --source pdf
pixi run ragdoll search "authentication token refresh" --source jira
```

---

## Complete Documentation

For detailed information on supported source types (PDF, Markdown, Git, AST Code, Jira, GitHub, Bitbucket), extraction schemas, CLI flags, and the `git` vs. `code` ingestion deep dive, see the **[Local Knowledge Staging & Batch Ingestion Guide](../docs/local-staging.md)** in the Sphinx documentation (`pixi run docs`).
