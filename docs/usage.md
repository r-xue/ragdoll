# Searching and Chatting

```bash
# Basic semantic search
pixi run ragdoll search "memory allocation regression"

# Filter by source
pixi run ragdoll search "embedding function" --source code
pixi run ragdoll search "memory allocation" --source pdf

# Control result count (`top_k`)
pixi run ragdoll search "database connection retry" -n 5
```

Results are displayed in a table with source ID, similarity score, and text preview.

```{note}
The `-n` flag controls the **`top_k`** retrieval parameter. This dictates how many chunks of text the vector database returns to you. Higher values give the LLM more context but can crowd the prompt context window, while lower values are faster but might miss necessary details. The default is configured to `5`.
```

## Summarizing

```bash
pixi run ragdoll summarize "What are the known issues with worker scaling?"
pixi run ragdoll summarize "task queue parallelization" --source jira
```

Summarization retrieves relevant chunks, injects them as context, and asks the
LLM to produce a structured summary with source citations.

## Interactive Chat

```bash
pixi run ragdoll chat
pixi run ragdoll chat --no-think            # Fast instant mode (thinking disabled)
pixi run ragdoll chat --think               # Deep reasoning mode (chain-of-thought enabled)
pixi run ragdoll chat --source jira
pixi run ragdoll chat --source code -n 12
```

### Chat Features

- **Multi-turn context & query condensation** — conversation history accumulates and follow-up references are automatically resolved
- **Conversational follow-ups** — ask follow-up questions like *"How many of them are open?"* without repeating project or repo names
- **Persistent history** — arrow-up/down recalls previous questions across
  sessions (stored in `~/.ragdoll/chat_history`, capped at 500 entries)
- **Full line editing** — backspace, arrow keys, Home/End all work
- **Source filtering** — `--source` limits retrieval to a specific data source
- **Streaming & Reasoning Control** — stream responses token-by-token with optional `--think` / `--no-think` runtime controls
- **Live Database Querying** — ask questions like *"List all open bugs for the PROJ project"* or *"Show me PRs by author"*. The Intent Router will detect this and automatically query the live Jira/Bitbucket APIs instead of the vector database.

### Multi-Turn Conversational Follow-ups

Ragdoll automatically resolves pronouns, ellipses, and implicit context across chat turns using background query condensation:

```text
You: How many tickets in the MYPROJ project?
Ragdoll: [Live JIRA Database] There are 3,136 total tickets in MYPROJ.

You: How many of them are open?
Ragdoll: [Generated JQL: project = MYPROJ AND statusCategory != Done]
There are 428 open tickets currently in MYPROJ.
```

### Chat Commands

| Input | Action |
| ------- | -------- |
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

- **Jira (Dynamic JQL Generation)**:
  > *"List all unresolved Critical bugs in the PROJ project updated in the last 7 days."*
  >
  > *(Ragdoll dynamically generates `project = PROJ AND priority = Critical AND resolution = Unresolved AND updated >= -7d` and queries your live Jira server).*

- **GitHub (Live Search API)**:
  > *"How many open pull requests are currently in myorg/myrepo?"*
  >
  > *(Ragdoll extracts `owner="myorg"`, `repo="myrepo"`, `state="open"`, `type="pr"`, queries GitHub's `/search/issues` endpoint, and returns the exact live count and recent PR details).*

- **Bitbucket (Live REST API)**:
  > *"Show me open pull requests for repo backend in project PROJ."*
  >
  > *(Ragdoll queries your Bitbucket Data Center REST API for active PRs and approval statuses).*

### 2. Knowledge Retrieval Queries (ChromaDB Vector Search)

When you ask conceptual, architectural, or debugging questions, Ragdoll performs semantic vector search over your offline ChromaDB database:

- *"How does the worker service handle failed tasks?"*
- *"Explain the function of the AST code chunker in `ragdoll.ingest.code`."*
- *"What was the resolution for the memory leak discussed in past Jira tickets?"*

## Global Options & CLI Syntax

Ragdoll commands follow a standard hierarchical structure:

```text
ragdoll [GLOBAL OPTIONS] <command | group> [SUBCOMMAND] [SUBCOMMAND OPTIONS]
```

### 1. Flag Placement Rules

- **Global Flags** (`-v`, `--verbose`, `--help`, `--version`): Place **directly after `ragdoll`**:

  ```bash
  # Correct global flag placement
  pixi run ragdoll -v ingest jira --server primary --jql "project = MYPROJ"
  pixi run ragdoll --verbose chat
  ```

- **Subcommand Options** (`--server`, `--jql`, `--max-results`, `--source`): Place **after the specific subcommand**:

  ```bash
  # Correct subcommand option placement
  pixi run ragdoll ingest jira --server primary --jql "project = MYPROJ" --max-results 100
  ```

```{note}
Because Click parses options strictly by command group, passing a global flag like `--verbose` after `ingest` (e.g. `ragdoll ingest --verbose ...`) will result in an unrecognized option error. Always place global flags directly after `ragdoll`.
```

### 2. Help Menus (`--help`)

View available commands, flags, and subcommand options:

```bash
# Top-level CLI help
pixi run ragdoll --help

# Subcommand-specific help & options
pixi run ragdoll ingest --help
pixi run ragdoll ingest jira --help
pixi run ragdoll search --help
```

### 3. Verbose / Debug Logging (`-v` / `--verbose`)

Enable detailed debug logs (including live batch progress and LLM routing traces):

```bash
# Debug live Jira ingestion with detailed pagination progress
pixi run ragdoll -v ingest jira --server primary --jql "project = MYPROJ"

# Debug live chat queries & LLM routing decisions
pixi run ragdoll -v chat

# Debug semantic search retrieval scores
pixi run ragdoll -v search "memory leak in buffer"
```

## Clearing the Vector Database (`clear`)

To remove all indexed documents and reset your vector database:

```bash
# Interactive confirmation prompt
pixi run ragdoll clear

# Force deletion without confirmation prompt
pixi run ragdoll clear --force
```

```{important}
**When should you clear the vector store?**
* **Switching Embedding Models**: If you change `embed_model` in `config.toml` (e.g. from `nomic-embed-text` to `bge-m3`), vector dimensions change. You **must** run `pixi run ragdoll clear --force` before re-ingesting.
* **Corrupted or Stale Indices**: If you want a fresh start or to completely purge previously ingested projects.
* *(Note: Switching `chat_model` does NOT require clearing the database).*
```

## Status

```bash
pixi run ragdoll status
```

Shows current configuration, vector store statistics, and available Ollama models.
