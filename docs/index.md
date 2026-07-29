# 🧶 Ragdoll

```{toctree}
---
maxdepth: 2
caption: Getting Started
hidden: true
---

getting-started
```

```{toctree}
---
maxdepth: 2
caption: Using Ragdoll
hidden: true
---

usage
web-ui
mcp-integration
```

```{toctree}
---
maxdepth: 2
caption: Administration & Data
hidden: true
---

configuration
ingestion
data-sources
```

```{toctree}
---
maxdepth: 2
caption: Under the Hood & Reference
hidden: true
---

architecture
api/index
extending
```

## Overview

**Ragdoll** (**R**etrieval-**A**ugmented **G**eneration **D**riven by **O**ffline **L**ocal **L**LMs) is a fully-local RAG system designed for engineering teams
who need to search, summarize, and reason over internal knowledge sources —
JIRA tickets, PDF documentation, and Python source code — without sending data
to external services.

### 🧭 Where should I go?

* **Just want to try it out?** Head to the [Getting Started](getting-started.md) guide.
* **Want to connect Ragdoll to Cursor/Windsurf?** Check out the [MCP Integration](mcp-integration.md).
* **Need to ingest your company's Jira or Bitbucket?** Read about [Ingesting Data](ingestion.md) and [Configuration](configuration.md).
* **Want to build on top of Ragdoll?** Dive into the [System Architecture](architecture.md), [API Reference](api/index.md), or learn about [Extending Ragdoll](extending.md).

### Key Features

- **Multi-source ingestion** — PDF, JIRA, Bitbucket, Git, and Python code
- **Semantic search** — ChromaDB vector store with cosine similarity
- **Local LLM** — Ollama-powered embedding and generation
- **Interactive chat** — Multi-turn RAG chat with persistent history
- **Privacy-first** — Everything runs locally; no external API calls
- **Flexible configuration** — 4-layer precedence (env → project → user → defaults)
