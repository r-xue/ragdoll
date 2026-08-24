# Knowledge Sources & Staging Area (`sources/`)

This directory is the **local staging area** for dropping documents and declaring manifests to index into Ragdoll.

> [!NOTE]
> All document contents placed inside `pdf/`, `markdown/`, and `repos/` (as well as custom subdirectories) are **excluded from Git** via `.gitignore`. They stay safely and privately on your local workstation.

---

## Directory Layout

```
sources/
 pdf/              # Place PDF technical memos, reports, manuals, and specs
 markdown/         # Place Markdown specifications, technical notes, and contracts
 repos/            # Local Git repository clones for code and commit analysis
 manifests/        # Declarative API and repository manifests
    ├── repos.txt     # Git repositories to clone and index (AST + Git commits)
    ├── jira.txt      # Jira JQL queries to fetch tickets and comments
    ├── github.txt    # GitHub repositories to fetch Issues and PR discussions
    └── bitbucket.txt # Bitbucket repositories to fetch PR reviews and discussions
```

---

## Quickstart

1. **Stage your sources**:
   * Copy `.pdf` files into `sources/pdf/`
   * Copy `.md` files into `sources/markdown/`
   * Declare Git repos in `sources/manifests/repos.txt` and run `pixi run ragdoll stage-repos`
   * Declare API queries in `sources/manifests/jira.txt`, `github.txt`, `bitbucket.txt`

2. **Run batch ingestion**:
   ```bash
   pixi run ragdoll ingest-all
   ```

3. **Start chatting**:
   ```bash
   pixi run ragdoll chat
   ```

---

## Complete Documentation

For detailed information on supported source types (PDF, Markdown, Git, AST Code, Jira, GitHub, Bitbucket), extraction schemas, CLI flags, and the `git` vs. `code` ingestion deep dive, see the **[Local Knowledge Staging & Batch Ingestion Guide](../docs/local-staging.md)** in the Sphinx documentation (`pixi run docs`).
