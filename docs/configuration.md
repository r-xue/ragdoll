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

# Model preferences
chat_model = "gpt-oss:20b"
embed_model = "nomic-embed-text"
temperature = 0.3

# Storage
data_dir = "/home/you/.ragdoll/data"
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
top_k = 12
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
RAGDOLL_TOP_K=20 pixi run ragdoll search "some query"
```

## Settings Reference

### JIRA

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `jira_url` | `str` | `"https://jira.example.com"` | JIRA server URL |
| `jira_user` | `str` | `""` | JIRA username |
| `jira_token` | `str` | `""` | API token or Personal Access Token |
| `jira_auth_method` | `str` | `"pat"` | `"pat"` (Data Center) or `"basic"` (Cloud) |
| `jira_batch_size` | `int` | `50` | Issues fetched per API call |

### Ollama / LLM

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `ollama_host` | `str` | `"http://localhost:11434"` | Ollama API endpoint |
| `embed_model` | `str` | `"nomic-embed-text"` | Model for computing embeddings |
| `chat_model` | `str` | `"gpt-oss:20b"` | Model for generation and chat |
| `temperature` | `float` | `0.3` | Sampling temperature |

### Storage

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `data_dir` | `Path` | `~/.ragdoll/data` | Root directory for ChromaDB |
| `collection_name` | `str` | `"ragdoll"` | ChromaDB collection name |

### Chunking & Retrieval

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `chunk_size` | `int` | `1000` | Max characters per chunk |
| `chunk_overlap` | `int` | `200` | Overlap between consecutive chunks |
| `top_k` | `int` | `20` | Default number of chunks to retrieve |

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

### Multiple JIRA Instances

The `~/.ragdoll/config.toml` file stores credentials for your **primary** JIRA
site. To ingest from additional sites, override the connection settings
directly on the CLI:

```bash
# Primary (uses config.toml defaults)
pixi run ragdoll ingest jira --jql "project = CAS"

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
