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
local-staging
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
* **Ready to search, summarize, or chat?** See [Searching and Chatting](usage.md) and the [Web UI](web-ui.md).
* **Want to connect Ragdoll to Claude/VS Code?** Check out the [MCP Integration](mcp-integration.md).
* **Need to ingest Jira, Bitbucket, GitHub, or Git?** Read about [Ingesting Data](ingestion.md), [Local Knowledge Staging](local-staging.md), and [Configuration](configuration.md).
* **Want to build on top of Ragdoll?** Dive into the [System Architecture](architecture.md), [API Reference](api/index.md), or learn about [Extending Ragdoll](extending.md).

### Key Features

- **Multi-source ingestion** — PDF, JIRA, Bitbucket, GitHub, Git, and Python code
- **Live Database Querying** — Automatic Intent Routing between ChromaDB vector search and real-time Jira JQL, GitHub Search, and Bitbucket APIs
- **Semantic search** — ChromaDB vector store with cosine similarity and metadata filtering
- **Local LLM** — Ollama-powered embedding and generation
- **Interactive chat** — Multi-turn RAG chat with persistent history and prompt grounding
- **Privacy-first** — Everything runs locally; no external API calls
- **Flexible configuration** — 4-layer precedence (env → project → user → defaults)
