# 📁 Local Knowledge Staging (`sources/`)

This directory is a **local staging area** for dropping documents and cloning repositories that you want to index into your Ragdoll vector database.

> [!NOTE]
> All document contents placed inside `pdf/`, `markdown/`, and `repos/` are **excluded from Git** via `.gitignore`. They will stay safely on your local workstation.

---

## 📂 Directory Layout

* **`sources/pdf/`**: Place your PDF technical memos, reports, architecture specifications, or user manuals here.
* **`sources/markdown/`**: Place Markdown specifications, technical notes, or API contracts here.
* **`sources/repos/`**: Clone external source code repositories here for code and Git commit history ingestion.

---

## 🚀 Quickstart: Staging & Ingestion

### Step 1: Stage Your Sources
* Copy your `.pdf` files into `sources/pdf/`
* Copy your `.md` files into `sources/markdown/`
* Add Git repo URLs to `sources/repos/repos.txt` and run `./scripts/clone_repos.sh`

### Step 2: Ingest into Vector Store
Run the automated ingestion script:
```bash
./scripts/ingest.sh
```

### Step 3: Start Chatting
```bash
pixi run ragdoll chat
```
