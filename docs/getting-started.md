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
ollama pull gpt-oss:20b          # chat model (Linux / Windows with NVIDIA)
# Or on Apple Silicon Mac:
# ollama pull qwen3.8:27b-mlx   # optimized for Apple Silicon MLX framework

# Verify models are available
ollama list
```

```{note}
`gpt-oss:20b` requires ~13 GB of VRAM. For a fully CPU-resident option, use a smaller model.
```

```{tip}
**Apple Silicon (M1/M2/M3/M4) Optimization with `-mlx` Tags:**

If you are running Ragdoll on an Apple Silicon Mac, consider pulling models with the `-mlx` tag (e.g. `qwen3.8:27b-mlx`, `gemma4:12b-mlx`).

- **Architecture**: Standard Ollama models use the GGUF format powered by `llama.cpp`. The `-mlx` variants run natively via Apple's **MLX machine learning framework**, designed exclusively for Apple Silicon.
- **Performance**: MLX models directly leverage Apple Silicon’s unified memory architecture and Metal GPU optimizations, delivering substantially faster token generation (eval rate), lower prompt-processing latency, and improved memory throughput.
- **Platform Compatibility**: `-mlx` models run exclusively on Apple Silicon macOS (M1/M2/M3/M4). (For Linux or Windows systems with NVIDIA GPUs, use standard GGUF models).
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
pixi run ragdoll --help
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
projects = ["CORE", "BACKEND"]

[jira_servers.secondary]
url = "https://secondary-jira.example.com"
user = "your.username"
token = "YOUR_PERSONAL_ACCESS_TOKEN"
auth_method = "pat"
projects = ["EXTERNAL", "TOOLS"]

# ==========================================
# 3. Bitbucket Server Configurations
# ==========================================

[bitbucket_servers.internal]
url = "https://bitbucket.example.com"
user = "your.username"
token = "YOUR_HTTP_ACCESS_TOKEN"
auth_method = "pat"

# ==========================================
# 4. GitHub Configurations
# ==========================================
github_token = "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN"
github_default_owner = "myorg"
github_repos = ["myorg/repo1", "myorg/repo2"]

[github_servers.enterprise]
url = "https://github.internal.mycompany.com/api/v3"
token = "YOUR_ENTERPRISE_TOKEN"
repos = ["internal-org/service"]
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

# Ingest GitHub issues and PR discussions
pixi run ragdoll ingest github myorg myrepo --state all

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
