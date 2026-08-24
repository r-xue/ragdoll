"""Repository staging and multi-source directory ingestion orchestrator.

Provides automated cloning/updating of external repositories from manifests
and recursive multi-source ingestion of PDF documents, Markdown specs,
and staged Git repositories into ChromaDB.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from rich.console import Console

from ragdoll.ingest.code import ingest_code
from ragdoll.ingest.git import ingest_git
from ragdoll.ingest.pdf import ingest_pdfs
from ragdoll.store.vectordb import get_index

logger = logging.getLogger(__name__)
console = Console()


def _get_working_dir() -> Path:
    """Get the user's effective working directory, respecting pixi/npm INIT_CWD."""
    init_cwd = os.environ.get("INIT_CWD")
    if init_cwd and Path(init_cwd).is_dir():
        return Path(init_cwd).resolve()
    return Path.cwd().resolve()


def stage_repositories(
    manifest_path: Path | str | None = None,
    target_dir: Path | str | None = None,
    pull: bool = True,
    depth: int | None = None,
) -> list[dict[str, Any]]:
    """Clone or update external Git repositories listed in a manifest file.

    Args:
        manifest_path (Path | str | None): Path to the repos.txt manifest file or folder.
        target_dir (Path | str | None): Target directory to clone repositories into.
        pull (bool): Whether to run git pull --ff-only on existing repositories.
        depth (int | None): Optional commit history depth for shallow clones.

    Returns:
        list[dict[str, Any]]: Status records for each repository in the manifest.
    """
    work_dir = _get_working_dir()
    manifest_file: Path | None = None

    # 1. Resolve manifest file
    if manifest_path is not None:
        p = Path(manifest_path)
        if not p.is_absolute():
            p = (work_dir / p).resolve()

        if p.is_file():
            manifest_file = p
        elif p.is_dir():
            for sub in [p / "repos.txt", p / "repos" / "repos.txt", p / "sources" / "repos" / "repos.txt"]:
                if sub.is_file():
                    manifest_file = sub.resolve()
                    break

    if manifest_file is None:
        for candidate in [
            work_dir / "repos" / "repos.txt",
            work_dir / "sources" / "repos" / "repos.txt",
            work_dir / "repos.txt",
            Path("sources/repos/repos.txt").resolve(),
            Path("repos/repos.txt").resolve(),
        ]:
            if candidate.is_file():
                manifest_file = candidate
                break

    if manifest_file is None or not manifest_file.is_file():
        raise FileNotFoundError(
            f"Repository manifest file not found: {manifest_path or 'repos/repos.txt'}. "
            "Please specify a valid manifest path or create repos/repos.txt."
        )

    # 2. Determine target directory
    if target_dir is None:
        target_dir_path = manifest_file.parent
    else:
        target_dir_p = Path(target_dir)
        if not target_dir_p.is_absolute():
            target_dir_p = (work_dir / target_dir_p).resolve()
        target_dir_path = target_dir_p

    target_dir_path.mkdir(parents=True, exist_ok=True)
    logger.info("Staging repositories from %s into %s", manifest_file, target_dir_path)

    results: list[dict[str, Any]] = []

    with open(manifest_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines:
        clean = line.strip()
        if not clean or clean.startswith("#"):
            continue

        parts = clean.split()
        url = parts[0]
        branch = parts[1] if len(parts) > 1 and parts[1] != "-" else None
        custom_dir = parts[2] if len(parts) > 2 else None

        # Derive repository folder name
        repo_name = custom_dir or Path(url.rstrip("/")).stem
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

        dest = target_dir_path / repo_name

        record = {
            "url": url,
            "branch": branch or "default",
            "name": repo_name,
            "path": dest,
            "status": "Unknown",
            "error": None,
        }

        try:
            if (dest / ".git").is_dir():
                if pull:
                    res = subprocess.run(
                        ["git", "-C", str(dest), "pull", "--ff-only"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if res.returncode == 0:
                        if "Already up to date" in res.stdout:
                            record["status"] = "Up to date"
                        else:
                            record["status"] = "Updated"
                    else:
                        record["status"] = "Pull failed"
                        record["error"] = res.stderr.strip()
                else:
                    record["status"] = "Skipped (exists)"
            else:
                clone_cmd = ["git", "clone"]
                if depth:
                    clone_cmd.extend(["--depth", str(depth)])
                if branch:
                    clone_cmd.extend(["--branch", branch])
                clone_cmd.extend([url, str(dest)])

                res = subprocess.run(
                    clone_cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res.returncode == 0:
                    record["status"] = "Cloned"
                else:
                    record["status"] = "Clone failed"
                    record["error"] = res.stderr.strip()

        except Exception as e:
            record["status"] = "Error"
            record["error"] = str(e)

        results.append(record)

    return results


def ingest_all_sources(
    root_path: Path | str = "sources",
    clone_first: bool = False,
) -> dict[str, int]:
    """Recursively ingest all PDF documents, Markdown specs, and staged code repositories.

    Args:
        root_path (Path | str): Root directory to inspect (e.g. 'sources/' or '/path/to/ragdoll-sources-pipeline').
        clone_first (bool): If True, runs stage_repositories on any found repos.txt before ingesting.

    Returns:
        dict[str, int]: Ingestion summary counts.
    """
    work_dir = _get_working_dir()
    root_p = Path(root_path)
    if not root_p.is_absolute():
        root_p = (work_dir / root_p).resolve()

    if not root_p.is_dir():
        raise NotADirectoryError(f"Target directory does not exist: {root_p}")

    summary = {
        "pdf_documents": 0,
        "markdown_documents": 0,
        "code_documents": 0,
        "git_commits": 0,
    }

    # 1. Optional Repository Staging
    if clone_first:
        manifest_candidates = [
            root_p / "repos" / "repos.txt",
            root_p / "sources" / "repos" / "repos.txt",
            root_p / "repos.txt",
        ]
        for mc in manifest_candidates:
            if mc.is_file():
                logger.info("Executing repository staging from manifest: %s", mc)
                stage_repositories(manifest_path=mc, target_dir=mc.parent)
                break

    # 2. Ingest PDF Documents
    pdf_candidates = [root_p / "pdf", root_p / "sources" / "pdf", root_p]
    pdf_dirs = [d for d in pdf_candidates if d.is_dir() and any(d.glob("*.pdf")) or any(d.rglob("*.pdf"))]
    if pdf_dirs:
        primary_pdf_dir = pdf_dirs[0]
        pdf_files = list(primary_pdf_dir.rglob("*.pdf"))
        if pdf_files:
            console.print(f"[bold cyan][1/3][/bold cyan] Ingesting {len(pdf_files)} PDF document(s) from [bold]{primary_pdf_dir}[/bold]...")
            count, skipped = ingest_pdfs(primary_pdf_dir)
            if skipped > 0 and count == 0:
                console.print(f"  ✨ All [green]{skipped}[/green] PDF(s) are already indexed and up-to-date.")
            elif skipped > 0:
                console.print(f"  💾 Stored [green]{count}[/green] new/updated chunks ([dim]{skipped} up-to-date skipped[/dim]).")
            summary["pdf_documents"] = count

    # 3. Ingest Markdown & Documentation Specifications
    md_candidates = [root_p / "markdown", root_p / "sources" / "markdown", root_p / "specs"]
    md_dirs = [d for d in md_candidates if d.is_dir()]
    if md_dirs:
        primary_md_dir = md_dirs[0]
        md_files = [f for f in primary_md_dir.rglob("*") if f.is_file() and f.suffix.lower() in {".md", ".markdown", ".rst", ".txt"}]
        if md_files:
            console.print(f"[bold cyan][2/3][/bold cyan] Ingesting {len(md_files)} Markdown document(s) from [bold]{primary_md_dir}[/bold]...")
            docs = ingest_code([primary_md_dir], extensions={".md", ".markdown", ".rst", ".txt"})
            if docs:
                index = get_index()
                index.insert_nodes(docs)
                summary["markdown_documents"] = len(docs)

    # 4. Ingest Staged Repositories
    repos_candidates = [root_p / "repos", root_p / "sources" / "repos"]
    repos_dirs = [d for d in repos_candidates if d.is_dir()]
    if repos_dirs:
        primary_repos_dir = repos_dirs[0]
        repo_subdirs = [d for d in primary_repos_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        if repo_subdirs:
            console.print(f"[bold cyan][3/3][/bold cyan] Ingesting {len(repo_subdirs)} staged repository(s) from [bold]{primary_repos_dir}[/bold]...")
            index = get_index()
            for rdir in repo_subdirs:
                # Ingest code AST
                console.print(f"  -> Ingesting source code AST for [bold]{rdir.name}[/bold]...")
                cdocs = ingest_code([rdir])
                if cdocs:
                    index.insert_nodes(cdocs)
                    summary["code_documents"] += len(cdocs)

                # Ingest git history if .git is present
                if (rdir / ".git").is_dir():
                    console.print(f"  -> Ingesting Git commit history for [bold]{rdir.name}[/bold]...")
                    commits_count = ingest_git(str(rdir))
                    summary["git_commits"] += commits_count

    return summary
