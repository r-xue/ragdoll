# Configuration

Ragdoll uses [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
with a **4-layer precedence** strategy. Higher-priority sources override lower ones.

## Precedence Order

```
1. RAGDOLL_* environment variables     (highest — CI / ephemeral overrides)
2a. ./ragdoll.toml                      (project-level settings)
2b. ./.env                              (project-level secrets)
3. ~/.ragdoll/config.toml               (user-level defaults & credentials)
4. Package defaults                     (lowest — hardcoded fallbacks)
```

## User Configuration

The recommended location for personal settings is `~/.ragdoll/config.toml`:

```toml
# ~/.ragdoll/config.toml

# JIRA connection
jira_url = "https://jira.example.com"
jira_user = "your.username"
jira_token = "YOUR_PERSONAL_ACCESS_TOKEN"
jira_auth_method = "pat"   # "pat" for JIRA Data Center, "basic" for Cloud

# GitHub connection
github_token = "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN"
github_url = "https://api.github.com" 

# Model preferences
chat_model = "gpt-oss:20b"          # Linux/Windows (or "qwen3.8:27b-mlx" on Apple Silicon)
embed_model = "nomic-embed-text"
temperature = 0.3
enable_thinking = false             # Set true to enable reasoning chain-of-thought

# Storage (optional - defaults to ~/.ragdoll/data)
# Uncomment to use a custom location with more space or faster disk:
# data_dir = "/mnt/nvme/ragdoll_data"
```

```{warning}
This file contains credentials. Protect it with `chmod 600 ~/.ragdoll/config.toml`.
```

## Project Configuration

For project-specific settings, create `ragdoll.toml` in your working directory:

```toml
# ragdoll.toml (project-level, commit to git)
collection_name = "my-project"
chunk_size = 800
chunk_overlap = 150
top_k = 5
```

For project-level secrets, use a `.env` file (add to `.gitignore`):

```bash
# .env (project-level secrets, do NOT commit)
RAGDOLL_JIRA_TOKEN=your_token_here
```

## Environment Variables

Any setting can be overridden via environment variables prefixed with `RAGDOLL_`:

```bash
RAGDOLL_CHAT_MODEL=gpt-oss:20b pixi run ragdoll chat
RAGDOLL_TOP_K=5 pixi run ragdoll search "some query"
```

## Retrieval Tuning & Context Sizing (`top_k`)

The `top_k` setting controls the number of context chunks retrieved from ChromaDB for each query or chat turn (default: **`5`**).

```toml
# ~/.ragdoll/config.toml
top_k = 5
```

### Context Sizing Trade-Offs

In local RAG systems, tuning `top_k` balances **context coverage** against **GPU prefill latency and answer precision**:

| Setting | Estimated Tokens | Prefill Time (RTX 3090) | Recommended Use Case |
| --- | --- | --- | --- |
| **`top_k = 5`** *(Default)* | ~2,000–3,500 tokens | **< 1.0s** | **Interactive Chat (`ragdoll chat`)**: Fast, snappy streaming with high precision. |
| **`top_k = 10`** | ~4,000–7,000 tokens | **1.0–2.5s** | **Summarization (`ragdoll summarize`) & Search**: Broader cross-document synthesis. |
| **`top_k = 20`** | ~10,000–25,000 tokens | **5.0–15.0s** | **Deep Archival Audits**: Exhaustive coverage across large multi-year ticket histories. |

```{tip}
**Ad-Hoc CLI Override:** You can override `top_k` on any command using `-n` without editing configuration files:
```bash
# Retrieve top 10 chunks for a broad search
pixi run ragdoll search "memory allocation in buffer" -n 10

# Fast conversational chat with top 3 chunks
pixi run ragdoll chat -n 3
```

```

## Switching Models (Chat vs. Embedding)

Ragdoll decouples your **Generative / Chat Model** from your **Embedding Model**:

### 1. Changing Chat Models (`chat_model`)

* **Impact**: **Instant, zero re-indexing required.**
* **Behavior**: The chat model is used purely at query time for intent routing, JQL generation, and answer synthesis. You can change `chat_model` at any time:

  ```toml
  chat_model = "qwen3.6:27b"
  ```

  or via environment variable:

  ```bash
  RAGDOLL_CHAT_MODEL=qwen3.6:27b pixi run ragdoll chat
  ```

### 2. Changing Embedding Models (`embed_model`)

* **Impact**: **Requires clearing the vector database and re-ingesting.**
* **Behavior**: Embedding models (e.g. `nomic-embed-text` at 768 dimensions vs `bge-m3` at 1024 dimensions) create vectors in different mathematical spaces. ChromaDB collections cannot mix incompatible vector dimensions.
* **Workflow to switch embedding models**:

  ```bash
  # 1. Update embed_model in ~/.ragdoll/config.toml
  # embed_model = "bge-m3"
  # or
  # embed_model = "qwen3-embedding:0.6b"

  # 2. Clear the old vector database
  pixi run ragdoll clear --force

  # 3. Re-run your ingestion scripts
  pixi run ragdoll ingest ...
  ```

## Fast Mode vs. Deep Reasoning Mode

Ragdoll supports both **Fast Instruction Models** and **Deep Reasoning Models** via [Ollama](https://ollama.com) (see [Ollama Reasoning Models Guide](https://docs.ollama.com/capabilities/thinking)):

| Mode | Best For | Typical Speed | Configuration / Flag |
| --- | --- | --- | --- |
| **Fast Mode (Default)** | Everyday Q&A, ticket counts, Jira/GitHub lookups, document search. | **< 1–2 seconds** | `enable_thinking = false` (or `--no-think`) |
| **Deep Reasoning Mode** | Complex debugging, architectural trade-offs, multi-document synthesis. | **15–30 seconds** | `enable_thinking = true` (or `--think`) |

### Why Reasoning Mode Takes Longer

When thinking mode is enabled, the model generates hundreds of hidden chain-of-thought tokens in the background before emitting its first visible word. Disabling thinking mode (`enable_thinking = false` or `--no-think`) skips the background scratchpad and streams the answer immediately.

```{note}
**Automatic Internal Acceleration:** Ragdoll always executes behind-the-scenes helper tasks (query condensation, intent routing, and JQL translation) in Fast Mode. Internal database lookups always complete in milliseconds regardless of user chat mode.
```

## Hardware & Model Selection Guide

Ragdoll supports Ollama-compatible embedding and chat models. The tables below summarize tested configurations across representative developer desktop and laptop environments.

### 1. Embedding Models

| Model | Size | Dimensions | Context | Notes |
| --- | --- | --- | --- | --- |
| **`bge-m3`** | 1.2 GB | 1024 | 8k | Default recommendation for technical docs, code, and Jira tickets. |
| **`qwen3-embedding:4b`** | ~2.5 GB | 2048 | 32k | High-capacity embeddings for large codebases and long documents. |
| **`qwen3-embedding:0.6b`** | ~0.6 GB | 1024 | 8k | Compact 1024-dim model for memory-constrained setups. |
| **`nomic-embed-text`** | 274 MB | 768 | 2k | Lightweight baseline model. |

### 2. Recommended Chat Models by Hardware Profile

| Hardware Profile (Representative Environments) | Usable Memory | Fast / Low Latency | Reasoning & Code |
| --- | --- | --- | --- |
| **Dedicated GPU Desktop / Workstation** *(e.g. RTX 3090 / 4090, 24 GB)* | 24 GB dedicated | `gemma4:12b` (~85 tok/s) | `qwen3.8` (27B, ~32 tok/s) |
| **Mainstream Apple Silicon Mac** *(e.g. M2 / M3 Pro, 32 GB)* | ~24 GB Metal | `gemma4:12b` (~40 tok/s) | `qwen3.8` (27B, ~16 tok/s) |
| **High-Memory Apple Silicon Mac** *(e.g. M4 Pro / Max, 48 GB)* | ~36 GB Metal | `gemma4:26b` (MoE, ~55 tok/s) | `gemma4:31b` or `qwen3.8` |

```{note}
**Note on `gpt-oss:20b` (Default Configuration)**
`gpt-oss:20b` (~13 GB) serves as a balanced general-purpose model with reliable query routing and solid synthesis at ~40–50 tok/s. While it is not highlighted in the table above, it remains a capable out-of-the-box baseline. Developers seeking higher interactive streaming speeds and larger context windows typically prefer `gemma4:12b`, while those requiring deeper technical reasoning and code analysis lean toward `qwen3.8`.
```

## Performance & Concurrency Tuning

When performing heavy ingestion tasks while simultaneously running `ragdoll chat`, Ollama can bottleneck or hang if it swaps back and forth between the embedding model (e.g. `nomic-embed-text` or `qwen3-embedding`) and the chat model (e.g. `gpt-oss:20b` or `qwen3.5:9b`).

### 1. Ollama Concurrency & Model Residency

Configure Ollama to keep multiple models in memory and handle parallel requests:

| Environment Variable | Recommended Value | Purpose |
| :--- | :--- | :--- |
| `OLLAMA_MAX_LOADED_MODELS` | `2` or `3` | Keeps both chat and embedding models resident in memory without swapping. |
| `OLLAMA_NUM_PARALLEL` | `2` or `4` | Allows chatting while ingestion is actively embedding chunks in parallel. |
| `OLLAMA_KEEP_ALIVE` | `-1` | Keeps models warm in memory indefinitely (no idle unload delay). |
| `OLLAMA_FLASH_ATTENTION` | `1` | Enables Flash Attention to reduce KV-cache memory and accelerate generation. |
| `OLLAMA_MAX_QUEUE` | `512` | Increases request queue buffer during bulk ingestion. |

#### Applying on macOS (Ollama GUI App)
macOS GUI apps do not inherit shell configuration (`~/.zshrc`). Set them via `launchctl`:
```bash
launchctl setenv OLLAMA_MAX_LOADED_MODELS 3
launchctl setenv OLLAMA_NUM_PARALLEL 4
launchctl setenv OLLAMA_KEEP_ALIVE -1
launchctl setenv OLLAMA_FLASH_ATTENTION 1
launchctl setenv OLLAMA_MAX_QUEUE 512
```
*After running these commands, quit Ollama completely from the menu bar and relaunch it.*

#### Applying on macOS / Linux (Terminal / CLI Server)
Add to your `~/.zshrc` or `~/.bashrc`:
```bash
export OLLAMA_MAX_LOADED_MODELS=3
export OLLAMA_NUM_PARALLEL=4
export OLLAMA_KEEP_ALIVE=-1
export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_MAX_QUEUE=512
```
Then start the server with `ollama serve`.

#### Applying on Linux (systemd Service)
```bash
sudo systemctl edit ollama.service
```
Add the following block:
```ini
[Service]
Environment="OLLAMA_MAX_LOADED_MODELS=3"
Environment="OLLAMA_NUM_PARALLEL=4"
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_MAX_QUEUE=512"
```
Reload and restart:
```bash
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

### 2. Apple Silicon Unified Memory Boost (macOS only)

By default, macOS caps the GPU/Metal framework from allocating more than ~75% of total physical RAM. For a Mac dedicated to running local models, you can raise the Metal wired memory ceiling to ~85–90%:

```bash
# Check current limit:
sysctl iogpu.wired_mem_limit

# Raise Metal memory limit (~85% of total RAM in MB):
# 32 GB RAM:
sudo sysctl iogpu.wired_mem_limit=27648
# 64 GB RAM:
sudo sysctl iogpu.wired_mem_limit=57344
# 128 GB RAM:
sudo sysctl iogpu.wired_mem_limit=114688
```

```bash
# Verify active models in memory:
ollama ps
```

## Settings Reference

### JIRA

| Key | Type | Default | Description |
| ----- | ------ | --------- | ------------- |
| `jira_url` | `str` | `"https://jira.example.com"` | JIRA server URL |
| `jira_user` | `str` | `""` | JIRA username |
| `jira_token` | `str` | `""` | API token or Personal Access Token |
| `jira_auth_method` | `str` | `"pat"` | `"pat"` (Data Center) or `"basic"` (Cloud) |
| `jira_batch_size` | `int` | `100` | Issues fetched per API call |

### GitHub

| Key | Type | Default | Description |
| ----- | ------ | --------- | ------------- |
| `github_url` | `str` | `"https://api.github.com"` | GitHub REST API endpoint |
| `github_token` | `str` | `""` | GitHub Personal Access Token (PAT) |
| `github_default_owner` | `str` | `""` | Default organization or owner for unqualified repo names in chat |

### Ollama / LLM

| Key | Type | Default | Description |
| ----- | ------ | --------- | ------------- |
| `ollama_host` | `str` | `"http://localhost:11434"` | Ollama API endpoint |
| `embed_model` | `str` | `"nomic-embed-text"` | Model for computing embeddings |
| `chat_model` | `str` | `"gpt-oss:20b"` | Model for generation and chat |
| `temperature` | `float` | `0.3` | Sampling temperature |
| `enable_thinking` | `bool` | `false` | Enable model reasoning/thinking mode (chain-of-thought) |

### Storage

| Key | Type | Default | Description |
| ----- | ------ | --------- | ------------- |
| `data_dir` | `Path` | `~/.ragdoll/data` | Root directory for local persistent data. ChromaDB is stored at `{data_dir}/chroma/` (used when `chroma_host` is not set) |
| `collection_name` | `str` | `"ragdoll"` | ChromaDB collection name |
| `chroma_host` | `str` | `None` | Remote ChromaDB server hostname or URL (e.g. `"http://chroma.internal"`). Enables Client-Server mode |
| `chroma_port` | `int` | `8000` | Remote ChromaDB server port |
| `chroma_ssl` | `bool` | `False` | Whether to use SSL/HTTPS when connecting to remote ChromaDB |
| `chroma_auth_token` | `str` | `None` | Optional Bearer authentication token for secured remote ChromaDB instances |

```{tip}
**When to customize `data_dir`:**
- **Large datasets**: Move to a disk with more space (e.g., `/mnt/storage/ragdoll_data`)
- **Performance**: Use faster SSD storage (e.g., `/mnt/nvme/ragdoll`)
- **Multi-project isolation**: Separate vector databases per project
- **Network/shared storage**: Use NFS or shared drives for team collaboration

**Important:** Changing `data_dir` creates a fresh database. You'll need to re-ingest all data. To migrate existing data, manually copy the old directory to the new location before updating the config.
```

### Chunking & Retrieval

| Key | Type | Default | Description |
| ----- | ------ | --------- | ------------- |
| `chunk_size` | `int` | `1000` | Max characters per chunk |
| `chunk_overlap` | `int` | `200` | Overlap between consecutive chunks |
| `top_k` | `int` | `5` | Default number of chunks to retrieve |

### Multi-Server GitHub & Repository Mapping

You can configure public and enterprise GitHub servers in `~/.ragdoll/config.toml` along with registered `repos`:

```toml
# Default organization when owner is omitted in chat
github_default_owner = "myorg"

# Public GitHub
[github_servers.public]
url = "https://api.github.com"
token = "ghp_PUBLIC_TOKEN"
repos = ["myorg/repo1", "myorg/repo2", "myorg/repo3"]

# Enterprise GitHub Server
[github_servers.enterprise]
url = "https://github.internal.org/api/v3"
token = "ghp_ENTERPRISE_TOKEN"
repos = ["internal-org/service", "internal-org/deploy-tools"]
```

#### Grounding & Disambiguation

* **Repository Grounding**: When you ask *"Show open PRs in repo1"*, Ragdoll automatically resolves `myorg/repo1` from your known repos list and routes directly to the `public` server.
* **Default Owner**: If you ask about an unlisted repository without specifying an owner, Ragdoll applies `github_default_owner` automatically.

## JIRA Authentication

### Data Center (PAT)

JIRA Data Center uses **Personal Access Tokens** with Bearer authentication.
Generate one from your JIRA profile → Personal Access Tokens.

```toml
jira_auth_method = "pat"
jira_token = "YOUR_PAT"
# jira_user is not required for PAT auth
```

### Cloud (Basic)

JIRA Cloud uses username + API token with HTTP Basic auth. Generate an API
token from [Atlassian Account Settings](https://id.atlassian.com/manage-profile/security/api-tokens).

```toml
jira_auth_method = "basic"
jira_user = "you@example.com"
jira_token = "YOUR_API_TOKEN"
```

### Multiple JIRA Instances & Smart Project Routing

You can configure named Jira instances in `~/.ragdoll/config.toml`. Adding an optional `projects` list enables **Smart Server Routing** for live queries:

```toml
# Primary Jira instance
[jira_servers.primary]
url = "https://jira.primary.example.com"
token = "PAT_PRIMARY"
auth_method = "pat"
projects = ["CORE", "BACKEND", "PROJ"]

# Partner / External Jira instance
[jira_servers.partner]
url = "https://jira.partner.example.com"
token = "PAT_PARTNER"
auth_method = "pat"
projects = ["EXTERNAL", "INTEG"]
```

#### How Smart Routing Works

1. **Targeted Routing (Zero Probing)**: When a chat query specifies a project (e.g. *"Show bugs in CORE"*), Ragdoll parses `project = CORE` from the generated JQL and routes the request **only to the matching server** (`primary`). It will completely skip querying `partner`.
2. **Probing Fallback**: If a server does not define a `projects` list (or if the query is a general cross-project search), Ragdoll queries all available servers. Missing-project errors on non-hosting servers are caught silently without polluting your chat terminal.

### Ingestion from Additional Sites via CLI

To ingest from additional sites on the command line:
site. To ingest from additional sites, override the connection settings
directly on the CLI:

```bash
# Primary (uses config.toml defaults)
pixi run ragdoll ingest jira --jql "project = MAIN"

# Secondary Data Center instance
pixi run ragdoll ingest jira \
  --url https://other-jira.example.com \
  --token OTHER_PAT \
  --jql "project = EXT"

# Cloud instance with different auth
pixi run ragdoll ingest jira \
  --url https://company.atlassian.net \
  --user you@company.com \
  --token CLOUD_TOKEN \
  --auth-method basic \
  --jql "project = CLOUD"
```

CLI flags (`--url`, `--user`, `--token`, `--auth-method`) take the highest
precedence, overriding all config layers for that invocation only.

```{tip}
You can also use environment variables for scripting multi-site ingestion:

    RAGDOLL_JIRA_URL=https://other.example.com \
    RAGDOLL_JIRA_TOKEN=OTHER_PAT \
    pixi run ragdoll ingest jira --jql "project = EXT"
```

### Remote ChromaDB Server Configuration (Team Collaboration)

To connect Ragdoll to a centralized, shared ChromaDB server (eliminating local data duplication and enabling team-wide instant updates):

```toml
# ~/.ragdoll/config.toml (Client Configuration)
chroma_host = "http://ragdoll-server.internal"
chroma_port = 8000
chroma_auth_token = "OPTIONAL_BEARER_TOKEN"  # optional token authentication
```

#### Starting the Central ChromaDB Server

You can launch a standalone ChromaDB HTTP server using the built-in CLI command:

```bash
# Start ChromaDB vector server on host 0.0.0.0:8000
pixi run ragdoll serve-chroma --host 0.0.0.0 --port 8000

# Or specify a custom storage directory
pixi run ragdoll serve-chroma --host 0.0.0.0 --port 8000 --path /secure/shared/chroma_db
```

```{seealso}
For a detailed architectural breakdown of how GPU, CPU, memory, and network loads are split between client workstations and the remote ChromaDB server, see [Deployment Topologies & Workload Distribution](architecture.md#deployment-topologies--workload-distribution) in the Architecture guide.
```

## Security, Privacy & Storage Considerations

Ragdoll persists all document chunk embeddings and metadata in a local [ChromaDB](https://www.trychroma.com/) collection.

### Plaintext Storage in ChromaDB

By design, ChromaDB couples an HNSW vector index with an embedded SQLite database (`chroma.sqlite3`). The SQLite database stores:

* **Full raw document chunks in plaintext** (parsed source code, Jira ticket discussions, PR reviews, PDF text).
* **All accompanying metadata** (file paths, author usernames, repository names, timestamps).

```{warning}
**Never commit or publicly share raw ChromaDB storage directories (`~/.ragdoll/data/` or `chroma.sqlite3`)!**

Anyone with access to the `chroma.sqlite3` database file can open it with standard SQLite tools to inspect and extract all ingested source text and metadata directly.
```

### Team Collaboration & Sharing Best Practices

* **Share Ingestion Recipes, Not Raw Databases**: Distribute project configuration (`ragdoll.toml`) and ingestion scripts (`scripts/examples.sh`) so each team member builds their own local vector database from sources they are already authorized to access.
* **Restrict File Permissions**:

  ```bash
  chmod 700 ~/.ragdoll
  chmod 600 ~/.ragdoll/config.toml
  ```

* **Git Exclusion**: Verify that `.sqlite3`, `.ragdoll/`, and local data directories are always excluded in `.gitignore`.
