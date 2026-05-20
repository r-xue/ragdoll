# 🧶 Ragdoll

```{toctree}
---
maxdepth: 2
caption: User Guide
hidden: true
---

getting-started
usage
web-ui
configuration
```

```{toctree}
---
maxdepth: 2
caption: Architecture
hidden: true
---

architecture
data-sources
```

```{toctree}
---
maxdepth: 2
caption: API Reference
hidden: true
---

api/index
```

## Overview

**Ragdoll** (**R**etrieval-**A**ugmented **G**eneration **D**riven by **O**ffline **L**ocal **L**LMs) is a fully-local RAG system designed for engineering teams
who need to search, summarize, and reason over internal knowledge sources —
JIRA tickets, PDF documentation, and Python source code — without sending data
to external services.

### Key Features

- **Multi-source ingestion** — PDF, JIRA, and Python code (AST-parsed)
- **Semantic search** — ChromaDB vector store with cosine similarity
- **Local LLM** — Ollama-powered embedding and generation
- **Interactive chat** — Multi-turn RAG chat with persistent history
- **Privacy-first** — Everything runs locally; no external API calls
- **Flexible configuration** — 4-layer precedence (env → project → user → defaults)
