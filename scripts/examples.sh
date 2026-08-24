#!/usr/bin/env bash
# ==============================================================================
# Ragdoll CLI Examples & Quick Reference
# ==============================================================================

# ------------------------------------------------------------------------------
# 0. One-Click Multi-Source Ingestion & Repository Staging
# ------------------------------------------------------------------------------
# Stage/clone external repositories declared in manifest:
# pixi run ragdoll stage-repos sources/manifests/repos.txt

# Ingest all staged PDFs, Markdown specs, and repositories in one pass:
# pixi run ragdoll ingest-all sources

# Automatically stage repositories and ingest all sources:
# pixi run ragdoll ingest-all sources --clone

# ------------------------------------------------------------------------------
# 1. Jira Ingestion (Incremental with Smart Server Targeting)
# ------------------------------------------------------------------------------
# Ingest via named server configuration in ~/.ragdoll/config.toml:
# pixi run ragdoll ingest jira --server primary --jql "project in (BACKEND, FRONTEND)"
# pixi run ragdoll ingest jira --server partner --jql "project = API"

# Ingest via direct CLI URL/Token override:
# pixi run ragdoll ingest jira --url https://jira.example.com --token "PAT" --jql "project = BACKEND"

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

# Semantic search across all sources:
# pixi run ragdoll search "memory allocation buffer" --source code
# pixi run ragdoll search "authentication token refresh" --source pdf

# ------------------------------------------------------------------------------
# 8. Services: Web UI, REST API, MCP Server
# ------------------------------------------------------------------------------
# Launch local Gradio Web UI:
# pixi run ragdoll ui --port 7860

# Launch MCP server over STDIO (Claude Desktop / Cursor):
# pixi run ragdoll mcp

# Launch OpenAI-compatible REST API:
# pixi run ragdoll serve --host 0.0.0.0 --port 8000

# ------------------------------------------------------------------------------
# 9. Central ChromaDB Vector Server (Team Sharing)
# ------------------------------------------------------------------------------
# Launch shared ChromaDB vector server:
# pixi run ragdoll serve-chroma --host 0.0.0.0 --port 8000
