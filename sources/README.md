# Knowledge Sources & Staging Area (`sources/`)

This directory is the **local staging area** for dropping documents and cloning repositories to index into Ragdoll.

> [!NOTE]
> All document contents placed inside `pdf/`, `markdown/`, and `repos/` (as well as custom subdirectories) are **excluded from Git** via `.gitignore`. They stay safely and privately on your local machine.

---

## Directory Layout

```
sources/
├── pdf/              # Place PDF technical memos, reports, manuals, and specs
├── markdown/         # Place Markdown specifications, technical notes, and contracts
└── repos/            # Clone Git repositories for code and commit history analysis
```

---

## Quickstart

1. **Stage your sources**:
   * Copy `.pdf` files into `sources/pdf/`
   * Copy `.md` files into `sources/markdown/`
   * Add Git repository URLs to `sources/repos/repos.txt` and run `./scripts/clone_repos.sh`

2. **Run batch ingestion**:
   ```bash
   ./scripts/ingest.sh
   ```

3. **Start chatting**:
   ```bash
   pixi run ragdoll chat
   ```

---

## Complete Documentation

For detailed information on supported source types (PDF, Markdown, Git, AST Code, Jira, GitHub, Bitbucket), extraction schemas, CLI flags, and the `git` vs. `code` ingestion deep dive, see the **[Local Knowledge Staging & Batch Ingestion Guide](../docs/local-staging.md)** in the Sphinx documentation (`pixi run docs`).
