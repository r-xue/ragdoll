# Searching and Chatting

```bash
# Basic semantic search
pixi run ragdoll search "tclean performance regression"

# Filter by source
pixi run ragdoll search "embedding function" --source code
pixi run ragdoll search "calibration pipeline" --source pdf

# Control result count (`top_k`)
pixi run ragdoll search "bandpass flagging" -n 5
```

Results are displayed in a table with source ID, similarity score, and text preview.

```{note}
The `-n` flag controls the **`top_k`** retrieval parameter. This dictates how many chunks of text the vector database returns to you. Higher values give the LLM more context but can crowd the prompt context window, while lower values are faster but might miss necessary details. The default is configured to `20`.
```

## Summarizing

```bash
pixi run ragdoll summarize "What are the known issues with imaging?"
pixi run ragdoll summarize "tclean parallelization" --source jira
```

Summarization retrieves relevant chunks, injects them as context, and asks the
LLM to produce a structured summary with source citations.

## Interactive Chat

```bash
pixi run ragdoll chat
pixi run ragdoll chat --source jira
pixi run ragdoll chat --source code -n 12
```

### Chat Features

- **Multi-turn context** — conversation history accumulates within a session
- **Persistent history** — arrow-up/down recalls previous questions across
  sessions (stored in `~/.ragdoll/chat_history`, capped at 500 entries)
- **Full line editing** — backspace, arrow keys, Home/End all work
- **Source filtering** — `--source` limits retrieval to a specific data source
- **Streaming** — responses are streamed token-by-token
- **Live Database Querying** — ask questions like *"List all open bugs for the PROJ project"* or *"Show me PRs by author"*. The Intent Router will detect this and automatically query the live Jira/Bitbucket APIs instead of the vector database.

### Chat Commands

| Input | Action |
|-------|--------|
| `quit` / `exit` / `q` | End the session |
| `Ctrl+C` | End the session |
| Arrow up/down | Recall previous questions |

## Live Database Querying vs. Knowledge Search

During interactive chat (`pixi run ragdoll chat`), Ragdoll uses an **Intent Router** to automatically determine whether your question requires semantic search over historical documents or real-time querying against live external APIs:

### 1. Live Database Queries (Real-Time API Execution)
When you ask for current lists, unresolved tickets, PR reviews, or exact item counts, the router bypasses the offline vector database, dynamically generates native API parameters, and queries your configured servers in real time:

```{tip}
**Smart Project Routing:** You can map projects to specific Jira servers in `~/.ragdoll/config.toml` using `projects = ["PROJ1", "PROJ2"]`. Ragdoll will route live queries directly to the correct server without probing other instances.
```

* **Jira (Dynamic JQL Generation)**:
  > *"List all unresolved Critical bugs in the PROJ project updated in the last 7 days."*
  >
  > *(Ragdoll dynamically generates `project = PROJ AND priority = Critical AND resolution = Unresolved AND updated >= -7d` and queries your live Jira server).*

* **GitHub (Live Search API)**:
  > *"How many open pull requests are currently in myorg/myrepo?"*
  >
  > *(Ragdoll extracts `owner="myorg"`, `repo="myrepo"`, `state="open"`, `type="pr"`, queries GitHub's `/search/issues` endpoint, and returns the exact live count and recent PR details).*

* **Bitbucket (Live REST API)**:
  > *"Show me open pull requests for repo backend in project PROJ."*
  >
  > *(Ragdoll queries your Bitbucket Data Center REST API for active PRs and approval statuses).*

### 2. Knowledge Retrieval Queries (ChromaDB Vector Search)
When you ask conceptual, architectural, or debugging questions, Ragdoll uses `VectorIndexAutoRetriever` to perform semantic vector search over your offline ChromaDB database:

* *"How does the calibration pipeline handle flagged antennas?"*
* *"Explain the function of the AST code chunker in `ragdoll.ingest.code`."*
* *"What was the resolution for the memory leak discussed in past Jira tickets?"*

## Status

```bash
pixi run ragdoll status
```

Shows current configuration, vector store statistics, and available Ollama models.
