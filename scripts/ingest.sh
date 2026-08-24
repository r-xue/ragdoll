#!/usr/bin/env bash
# ==============================================================================
# Ragdoll Automated Local Ingestion Helper
# Ingests all staged PDFs, Markdown specs, and repositories from sources/
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCES_DIR="${REPO_ROOT}/sources"

echo "=============================================================================="
echo "🧶 Ragdoll Local Knowledge Ingestion"
echo "  Staging Directory: ${SOURCES_DIR}"
echo "=============================================================================="

# 1. Ingest PDF documentation
if [ -d "${SOURCES_DIR}/pdf" ] && [ "$(find "${SOURCES_DIR}/pdf" -name "*.pdf" | wc -l)" -gt 0 ]; then
    echo -e "\n[1/3] Ingesting PDF technical documentation..."
    pixi run ragdoll ingest pdf "${SOURCES_DIR}/pdf"
else
    echo -e "\n[1/3] No PDF files found in sources/pdf (skipping)."
fi

# 2. Ingest Markdown documentation
if [ -d "${SOURCES_DIR}/markdown" ] && [ "$(find "${SOURCES_DIR}/markdown" -name "*.md" ! -name ".gitkeep" | wc -l)" -gt 0 ]; then
    echo -e "\n[2/3] Ingesting Markdown technical specifications..."
    pixi run ragdoll ingest code "${SOURCES_DIR}/markdown"
else
    echo -e "\n[2/3] No Markdown files found in sources/markdown (skipping)."
fi

# 3. Ingest Staged Code Repositories
if [ -d "${SOURCES_DIR}/repos" ]; then
    staged_repos=$(find "${SOURCES_DIR}/repos" -mindepth 1 -maxdepth 1 -type d ! -name ".*")
    if [ -n "${staged_repos}" ]; then
        echo -e "\n[3/3] Ingesting staged code repositories and git histories..."
        for repo_dir in ${staged_repos}; do
            repo_name="$(basename "${repo_dir}")"
            echo -e "\n  -> Ingesting source code for [${repo_name}]..."
            pixi run ragdoll ingest code "${repo_dir}"
            
            if [ -d "${repo_dir}/.git" ]; then
                echo -e "  -> Ingesting Git commit history for [${repo_name}]..."
                pixi run ragdoll ingest git "${repo_dir}"
            fi
        done
    else
        echo -e "\n[3/3] No repositories found in sources/repos (skipping)."
    fi
fi

echo -e "\nIngestion complete! Launch chat with: pixi run ragdoll chat"
