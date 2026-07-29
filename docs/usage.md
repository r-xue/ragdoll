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

> [!NOTE]
> The `-n` flag controls the **`top_k`** retrieval parameter. This dictates how many chunks of text the vector database returns to you. Higher values give the LLM more context but can crowd the prompt context window, while lower values are faster but might miss necessary details. The default is configured to `20`.

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
- **Live Database Querying** — ask questions like *"List all open bugs for the PIPE project"* or *"Show me PRs by rxue"*. The Intent Router will detect this and automatically query the live Jira/Bitbucket APIs instead of the vector database.

### Chat Commands

| Input | Action |
|-------|--------|
| `quit` / `exit` / `q` | End the session |
| `Ctrl+C` | End the session |
| Arrow up/down | Recall previous questions |

## Status

```bash
pixi run ragdoll status
```

Shows current configuration, vector store statistics, and available Ollama models.
