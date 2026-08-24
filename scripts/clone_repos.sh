#!/usr/bin/env bash
# ==============================================================================
# Clone / Update External Repositories Listed in sources/repos/repos.txt
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPOS_DIR="${REPO_ROOT}/sources/repos"
MANIFEST="${REPOS_DIR}/repos.txt"

if [ ! -f "${MANIFEST}" ]; then
    echo "Error: Manifest file not found at ${MANIFEST}"
    exit 1
fi

echo "=============================================================================="
echo "Cloning / Updating Staged Repositories from ${MANIFEST}"
echo "=============================================================================="

while IFS= read -r line || [ -n "$line" ]; do
    line="$(echo "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    [[ -z "$line" || "$line" =~ ^# ]] && continue

    read -r url branch custom_dir <<< "$line"

    repo_name="${custom_dir:-$(basename "${url}" .git)}"
    target_dir="${REPOS_DIR}/${repo_name}"

    if [ -d "${target_dir}/.git" ]; then
        echo -e "\nUpdating existing repository: [${repo_name}]..."
        (cd "${target_dir}" && git pull --ff-only || echo "Warning: Could not fast-forward ${repo_name}")
    else
        echo -e "\nCloning repository: [${repo_name}] from ${url}..."
        if [ -n "${branch:-}" ]; then
            git clone --branch "${branch}" "${url}" "${target_dir}"
        else
            git clone "${url}" "${target_dir}"
        fi
    fi
done < "${MANIFEST}"

echo -e "\nRepository staging completed in: ${REPOS_DIR}"
