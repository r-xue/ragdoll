#!/usr/bin/env bash
# ==============================================================================
# Ragdoll CLI Examples & Quick Reference
# ==============================================================================
# NOTE: If you are running commands from OUTSIDE the ragdoll codebase directory
# (such as from an external data sources repository),
# specify the path to ragdoll using pixi's -m / --manifest-path flag:
#
#   pixi run -m /path/to/ragdoll ragdoll <command>
#   # Or relative path:
#   pixi run -m ../ragdoll ragdoll ingest-all . --clone
# ==============================================================================

# ------------------------------------------------------------------------------
# 0. One-Click Multi-Source Ingestion & Repository Staging
# ------------------------------------------------------------------------------
# Ingest all sources in one pass:
# (Scans local pdf/, markdown/, already-staged repos/, and queries Jira/GitHub/Bitbucket APIs via manifests/)
# pixi run ragdoll ingest-all sources

# Full Sync & Ingestion (Recommended):
# (1. First runs stage-repos to clone/pull Git repos from manifests/repos.txt into repos/)
# (2. Then indexes pdf/, markdown/, repos/ code AST + commits, and all live API manifests)
# pixi run ragdoll ingest-all sources --clone

# Stage/pull Git repositories declared in manifest ONLY (no indexing):
# pixi run ragdoll stage-repos sources/manifests/repos.txt

# Stage/download remote PDF documents declared in manifest ONLY (no indexing):
# pixi run ragdoll stage-pdfs sources/manifests/pdf.txt

# Run from an external sources repository (e.g. sibling data workspace):
# pixi run -m ../ragdoll ragdoll ingest-all . --clone
# pixi run --manifest-path /path/to/ragdoll ragdoll ingest-all .

# ------------------------------------------------------------------------------
# 1. Jira Ingestion (Incremental with Smart Server Targeting)
# ------------------------------------------------------------------------------
# Ingest via named server configuration in ~/.ragdoll/config.toml:
# pixi run ragdoll ingest jira --server primary --jql "project in (BACKEND, FRONTEND)"
# pixi run ragdoll ingest jira --server partner --jql "project = API"

# Ingest via direct CLI URL/Token override:
# pixi run ragdoll ingest jira --url https://jira.example.com --token "PAT" --jql "project = BACKEND"

# From external workspace:
# pixi run -m ../ragdoll ragdoll ingest jira --server primary --jql "project = BACKEND"

# ------------------------------------------------------------------------------
# 2. GitHub Issues & Pull Requests
# ------------------------------------------------------------------------------
# Ingest open and closed issues/PRs with full comment threads:
# pixi run ragdoll ingest github --owner myorg --repo web-app --state all
# pixi run ragdoll ingest github --owner myorg --repo data-service --state open

# ------------------------------------------------------------------------------
# 3. Bitbucket Server Pull Requests
# ------------------------------------------------------------------------------
# pixi run ragdoll ingest bitbucket --project APP --repo backend-service --state ALL

# ------------------------------------------------------------------------------
# 4. Multi-Language Source Code Ingestion (Python, C/C++, Fortran, Shell, Build)
# ------------------------------------------------------------------------------
# Ingest full repository source trees:
# pixi run ragdoll ingest code sources/repos/web-app

# Filter specific language extensions:
# pixi run ragdoll ingest code sources/repos/web-app --ext cpp,cc,h,hpp,py

# ------------------------------------------------------------------------------
# 5. Git Commit History Ingestion (Incremental with Hash Skipping)
# ------------------------------------------------------------------------------
# Ingest recent commits (default 2000):
# pixi run ragdoll ingest git sources/repos/web-app

# Ingest full repository history:
# pixi run ragdoll ingest git sources/repos/web-app --all

# Exclude merge commits:
# pixi run ragdoll ingest git sources/repos/web-app --no-merges

# ------------------------------------------------------------------------------
# 6. PDF Documentation & Whitepapers
# ------------------------------------------------------------------------------
# pixi run ragdoll ingest pdf sources/pdf

# ------------------------------------------------------------------------------
# 7. Interactive RAG Chat & Semantic Search
# ------------------------------------------------------------------------------
# Launch interactive chat session:
# pixi run ragdoll chat

# Chat with customized top_k context chunks:
# pixi run ragdoll chat -n 5

# Semantic search across all sources:
# pixi run ragdoll search "memory allocation buffer" --source code
# pixi run ragdoll search "authentication token refresh" --source pdf

# ------------------------------------------------------------------------------
# 8. Services: Web UI, REST API, MCP Server
# ------------------------------------------------------------------------------
# Launch local Gradio Web UI:
# pixi run ragdoll ui --port 7860

# Launch MCP server over STDIO (for Claude Desktop integration)
# pixi run ragdoll mcp

# Launch MCP server over SSE (HTTP Server-Sent Events)
# pixi run ragdoll mcp --transport sse --port 8080

# Launch OpenAI-compatible REST API:
# pixi run ragdoll serve --host 0.0.0.0 --port 8000

# ------------------------------------------------------------------------------
# 9. Central ChromaDB Vector Server (Team Sharing)
# ------------------------------------------------------------------------------
# Launch shared ChromaDB vector server:
# pixi run ragdoll serve-chroma --host 0.0.0.0 --port 8000
