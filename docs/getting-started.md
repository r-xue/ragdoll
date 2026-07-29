# Getting Started

## Prerequisites

Before using Ragdoll, ensure you have:

1. **Python 3.12+**
2. **[Ollama](https://ollama.ai)** installed and running
3. **[pixi](https://pixi.sh)** for environment management

### Setting Up Ollama

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull the required models
ollama pull nomic-embed-text    # embedding model
ollama pull gpt-oss:20b          # chat model (or a smaller alternative)

# Verify models are available
ollama list
```

```{note}
`gpt-oss:20b` requires ~13 GB of VRAM. For a fully CPU-resident option, use a smaller model.
```

## Installation

```bash
# Clone the repository
git clone <repo-url> ragdoll
cd ragdoll

# Install with pixi
pixi install

# Verify the installation
pixi run ragdoll --version
pixi run ragdoll status
```

## Initial Configuration

Create your user-level configuration file:

```bash
mkdir -p ~/.ragdoll && chmod 700 ~/.ragdoll
cat > ~/.ragdoll/config.toml << 'EOF'
# ==========================================
# 1. Global / Top-Level Settings
# (Must be at the very top of the file)
# ==========================================
chat_model = "gpt-oss:20b"
embed_model = "nomic-embed-text"
chunk_size = 1000

# ==========================================
# 2. Jira Server Configurations
# (Nested dictionary blocks go below globals)
# ==========================================

[jira_servers.primary]
url = "https://primary-jira.example.com"
user = "your.username"
token = "YOUR_PERSONAL_ACCESS_TOKEN"
auth_method = "pat"

[jira_servers.secondary]
url = "https://secondary-jira.example.com"
user = "your.username"
token = "YOUR_PERSONAL_ACCESS_TOKEN"
auth_method = "pat"

# ==========================================
# 3. Bitbucket Server Configurations
# ==========================================

[bitbucket_servers.internal]
url = "https://bitbucket.example.com"
user = "your.username"
token = "YOUR_HTTP_ACCESS_TOKEN"
auth_method = "pat"
EOF
chmod 600 ~/.ragdoll/config.toml
```

```{important}
Protect your config file with `chmod 600` — it contains your JIRA token.
```

## First Ingestion

```bash
# Ingest some PDF documentation
pixi run ragdoll ingest pdf ./path/to/docs/

# Ingest recent JIRA tickets
pixi run ragdoll ingest jira --jql "project = MYPROJ AND updated >= -30d"

# Ingest a Python codebase
pixi run ragdoll ingest code ./src/

# Check what was indexed
pixi run ragdoll status
```

## First Query

```bash
# Search
pixi run ragdoll search "how does the calibration pipeline work?"

# Summarize
pixi run ragdoll summarize "known performance issues"

# Interactive chat
pixi run ragdoll chat
```
