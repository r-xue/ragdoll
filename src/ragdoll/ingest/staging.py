"""Multi-source directory and API manifest ingestion orchestrator.

Provides automated cloning/updating of external repositories and unified
batch ingestion of local PDFs, Markdown specs, code ASTs, Git commits,
Jira tickets, GitHub Issues/PRs, and Bitbucket PRs from declarative manifests.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from rich.console import Console

from ragdoll.ingest.bitbucket import ingest_bitbucket
from ragdoll.ingest.code import ingest_code
from ragdoll.ingest.git import ingest_git
from ragdoll.ingest.github import ingest_github
from ragdoll.ingest.jira import ingest_jira
from ragdoll.ingest.pdf import ingest_pdfs
from ragdoll.store.vectordb import get_index

logger = logging.getLogger(__name__)
console = Console()


def get_working_dir() -> Path:
    """Get the user's effective working directory, respecting pixi/npm INIT_CWD."""
    init_cwd = os.environ.get("INIT_CWD")
    if init_cwd and Path(init_cwd).is_dir():
        return Path(init_cwd).resolve()
    return Path.cwd().resolve()


# Backward-compatible alias
_get_working_dir = get_working_dir


def _find_manifest(root_dir: Path, filename: str) -> Path | None:
    """Locate a manifest file inside manifests/ or sources/manifests/."""
    candidates = [
        root_dir / "manifests" / filename,
        root_dir / "sources" / "manifests" / filename,
        root_dir / filename,
        root_dir / "sources" / filename,
    ]
    for c in candidates:
        if c.is_file():
            return c.resolve()
    return None


def parse_repos_manifest(manifest_path: Path | str) -> dict[str, dict[str, Any]]:
    """Parse repos.txt manifest into a mapping of repo_name -> configuration.

    Supports format:
        <GIT_URL> [BRANCH] [OPTIONAL_DIR_NAME] [COMMITS_LIMIT]

    Where COMMITS_LIMIT can be:
        - 'all' / 'full' / '*' : Fetch and index all commits across all history
        - integer (e.g. 5000)   : Limit commit history to specified number of commits
        - '-' / omitted        : Defaults to standard 2000 commits

    Returns:
        dict[str, dict[str, Any]]: Dictionary mapping repo directory name to config dict.
    """
    manifest_p = Path(manifest_path)
    if not manifest_p.is_file():
        return {}

    configs: dict[str, dict[str, Any]] = {}
    with open(manifest_p, "r", encoding="utf-8") as f:
        for line in f:
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue

            parts = clean.split()
            url = parts[0]
            branch = parts[1] if len(parts) > 1 and parts[1] != "-" else None
            custom_dir = parts[2] if len(parts) > 2 and parts[2] != "-" else None
            commits_spec = parts[3] if len(parts) > 3 else None

            # Derive repository folder name
            repo_name = custom_dir or Path(url.rstrip("/")).stem
            if repo_name.endswith(".git"):
                repo_name = repo_name[:-4]

            all_commits = False
            max_commits = 2000
            if commits_spec:
                if commits_spec.lower() in ("all", "full", "*"):
                    all_commits = True
                    max_commits = 0
                elif commits_spec.isdigit():
                    max_commits = int(commits_spec)
                    all_commits = False

            configs[repo_name] = {
                "url": url,
                "branch": branch,
                "dir_name": repo_name,
                "all_commits": all_commits,
                "max_commits": max_commits,
            }
    return configs


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
    work_dir = get_working_dir()
    manifest_file: Path | None = None

    # 1. Resolve manifest file
    if manifest_path is not None:
        p = Path(manifest_path)
        if not p.is_absolute():
            p = (work_dir / p).resolve()

        if p.is_file():
            manifest_file = p
        elif p.is_dir():
            manifest_file = _find_manifest(p, "repos.txt")

    if manifest_file is None:
        manifest_file = _find_manifest(work_dir, "repos.txt")

    if manifest_file is None or not manifest_file.is_file():
        raise FileNotFoundError(
            f"Repository manifest file not found: {manifest_path or 'manifests/repos.txt'}. "
            "Please specify a valid manifest path or create manifests/repos.txt."
        )

    # 2. Determine target directory
    if target_dir is None:
        # Default to a sibling repos/ folder if manifest is inside manifests/
        if manifest_file.parent.name == "manifests":
            target_dir_path = manifest_file.parent.parent / "repos"
        else:
            target_dir_path = manifest_file.parent
    else:
        target_dir_p = Path(target_dir)
        if not target_dir_p.is_absolute():
            target_dir_p = (work_dir / target_dir_p).resolve()
        target_dir_path = target_dir_p

    target_dir_path.mkdir(parents=True, exist_ok=True)
    logger.info("Staging repositories from %s into %s", manifest_file, target_dir_path)

    results: list[dict[str, Any]] = []
    repo_configs = parse_repos_manifest(manifest_file)

    for repo_name, cfg in repo_configs.items():
        url = cfg["url"]
        branch = cfg["branch"]
        dest = target_dir_path / repo_name

        record = {
            "url": url,
            "branch": branch or "default",
            "name": repo_name,
            "path": dest,
            "all_commits": cfg["all_commits"],
            "max_commits": cfg["max_commits"],
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


def stage_pdfs(
    manifest_path: Path | str | None = None,
    target_dir: Path | str | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Download and sync remote PDF documents declared in a manifest file (e.g. pdf.txt).

    Manifest line format:
        <URL> [OPTIONAL_SUBPATH_OR_FILENAME]

    Args:
        manifest_path (Path | str | None): Path to pdf.txt or directory containing manifests/.
        target_dir (Path | str | None): Destination directory (defaults to sibling pdf/ directory).
        force (bool): If True, forces re-download even if file exists locally.

    Returns:
        list[dict[str, Any]]: Download summary records.
    """
    work_dir = _get_working_dir()

    # 1. Resolve manifest file
    manifest_file: Path | None = None
    if manifest_path is not None:
        p = Path(manifest_path)
        if not p.is_absolute():
            p = (work_dir / p).resolve()
        if p.is_file():
            manifest_file = p
        elif p.is_dir():
            manifest_file = _find_manifest(p, "pdf.txt")

    if manifest_file is None:
        manifest_file = _find_manifest(work_dir, "pdf.txt")

    if manifest_file is None or not manifest_file.is_file():
        raise FileNotFoundError(
            f"PDF manifest file not found: {manifest_path or 'manifests/pdf.txt'}. "
            "Please specify a valid manifest path or create manifests/pdf.txt."
        )

    # 2. Determine target directory
    if target_dir is None:
        if manifest_file.parent.name == "manifests":
            target_dir_path = manifest_file.parent.parent / "pdf"
        else:
            target_dir_path = manifest_file.parent
    else:
        target_dir_p = Path(target_dir)
        if not target_dir_p.is_absolute():
            target_dir_path = (work_dir / target_dir_p).resolve()
        else:
            target_dir_path = target_dir_p.resolve()

    target_dir_path.mkdir(parents=True, exist_ok=True)
    logger.info("Staging PDFs from %s into %s", manifest_file, target_dir_path)

    # 3. Read and process manifest lines
    results: list[dict[str, Any]] = []
    lines = manifest_file.read_text(encoding="utf-8").splitlines()

    for line in lines:
        clean = line.strip()
        if not clean or clean.startswith("#"):
            continue

        parts = clean.split(maxsplit=1)
        url = parts[0]
        custom_subpath = parts[1] if len(parts) > 1 else None

        if custom_subpath:
            dest = target_dir_path / custom_subpath
        else:
            parsed_path = urllib.parse.urlparse(url).path
            filename = Path(parsed_path).name or "document.pdf"
            if not filename.lower().endswith(".pdf"):
                filename += ".pdf"
            dest = target_dir_path / filename

        dest.parent.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "url": url,
            "destination": dest,
            "status": "Unknown",
            "error": None,
        }

        try:
            if dest.is_file() and dest.stat().st_size > 0 and not force:
                record["status"] = "Up to date"
            else:
                logger.info("Downloading %s -> %s", url, dest)
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Ragdoll-Pipeline/1.0 (Python urllib)"},
                )
                part_dest = dest.with_suffix(dest.suffix + ".part")
                with urllib.request.urlopen(req, timeout=60) as resp, open(part_dest, "wb") as out_f:
                    while chunk := resp.read(64 * 1024):
                        out_f.write(chunk)
                part_dest.replace(dest)
                record["status"] = "Downloaded"
        except Exception as e:
            record["status"] = "Error"
            record["error"] = str(e)
            logger.warning("Failed to download %s: %s", url, e)

        results.append(record)

    return results


def ingest_all_sources(
    root_path: Path | str = "sources",
    clone_first: bool = False,
    force: bool = False,
    all_commits: bool = False,
) -> dict[str, int]:
    """Recursively ingest all data sources from physical directories and API manifests.

    Scans for:
    1. Local PDF documents (pdf/) with incremental SHA-256 caching.
    2. Local Markdown specifications (markdown/).
    3. Staged Git repositories (repos/) for code ASTs and commit histories.
    4. Jira query manifests (manifests/jira.txt).
    5. GitHub repository manifests (manifests/github.txt).
    6. Bitbucket repository manifests (manifests/bitbucket.txt).

    Args:
        root_path (Path | str): Root directory to inspect (e.g. 'sources/' or '/path/to/ragdoll-sources-pipeline').
        clone_first (bool): If True, runs stage_repositories on any found repos.txt before ingesting.
        force (bool): If True, forces full re-indexing of all data sources.
        all_commits (bool): If True, fetches full commit histories for all repositories (ignores limits).

    Returns:
        dict[str, int]: Ingestion summary counts across all source types.
    """
    work_dir = get_working_dir()
    root_p = Path(root_path)
    if not root_p.is_absolute():
        root_p = (work_dir / root_p).resolve()

    if not root_p.is_dir():
        raise NotADirectoryError(f"Target directory does not exist: {root_p}")

    # Pre-flight: detect corrupted ChromaDB before wasting time on staging/parsing.
    from ragdoll.store.safety import check_chromadb_health, GracefulInterrupt
    if not check_chromadb_health():
        raise RuntimeError(
            "ChromaDB database is corrupted. Run 'ragdoll clear --force' to reset, "
            "then re-ingest with --force."
        )

    summary = {
        "pdf_documents": 0,
        "markdown_documents": 0,
        "code_documents": 0,
        "git_commits": 0,
        "jira_tickets": 0,
        "github_items": 0,
        "bitbucket_prs": 0,
    }

    # 1. Optional Repository & PDF Staging
    repos_manifest = _find_manifest(root_p, "repos.txt")
    manifest_repo_configs = parse_repos_manifest(repos_manifest) if repos_manifest else {}

    if clone_first and repos_manifest:
        logger.info("Executing repository staging from manifest: %s", repos_manifest)
        target_dir = repos_manifest.parent.parent / "repos" if repos_manifest.parent.name == "manifests" else repos_manifest.parent
        stage_repositories(manifest_path=repos_manifest, target_dir=target_dir)

    pdf_manifest = _find_manifest(root_p, "pdf.txt")
    if clone_first and pdf_manifest:
        logger.info("Executing PDF download staging from manifest: %s", pdf_manifest)
        target_pdf_dir = pdf_manifest.parent.parent / "pdf" if pdf_manifest.parent.name == "manifests" else pdf_manifest.parent
        stage_pdfs(manifest_path=pdf_manifest, target_dir=target_pdf_dir, force=force)

    step = 1

    # 2. Ingest PDF Documents
    pdf_candidates = [root_p / "pdf", root_p / "sources" / "pdf", root_p]
    pdf_dirs = [d for d in pdf_candidates if d.is_dir() and (any(d.glob("*.pdf")) or any(d.rglob("*.pdf")))]
    if pdf_dirs:
        primary_pdf_dir = pdf_dirs[0]
        pdf_files = list(primary_pdf_dir.rglob("*.pdf"))
        if pdf_files:
            console.print(
                f"[bold cyan][{step}][/bold cyan] Ingesting {len(pdf_files)} PDF document(s) from [bold]{primary_pdf_dir}[/bold]...")
            try:
                count, skipped = ingest_pdfs(primary_pdf_dir, force=force)
                if skipped > 0 and count == 0:
                    console.print(f"  ✨ All [green]{skipped}[/green] PDF(s) are already indexed and up-to-date in ChromaDB.")
                elif skipped > 0:
                    console.print(f"  💾 Stored [green]{count}[/green] new/updated chunk(s) ([dim]{skipped} up-to-date skipped[/dim]).")
                summary["pdf_documents"] = count
            except Exception as e:
                console.print(f"  [yellow]Warning:[/yellow] PDF ingestion encountered an issue: {e}")
            step += 1

    # 3. Ingest Markdown & Documentation Specifications
    md_candidates = [root_p / "markdown", root_p / "sources" / "markdown", root_p / "specs"]
    md_dirs = [d for d in md_candidates if d.is_dir()]
    if md_dirs:
        primary_md_dir = md_dirs[0]
        md_files = [f for f in primary_md_dir.rglob("*") if f.is_file() and f.suffix.lower() in {".md", ".markdown", ".rst", ".txt"}]
        if md_files:
            console.print(
                f"[bold cyan][{step}][/bold cyan] Ingesting {len(md_files)} Markdown document(s) from [bold]{primary_md_dir}[/bold]...")
            try:
                res = ingest_code([primary_md_dir], extensions={".md", ".markdown", ".rst", ".txt"}, force=force)
                docs, skipped = res if isinstance(res, tuple) else (res, 0)
                if skipped > 0 and not docs:
                    console.print(f"  ✨ All [green]{skipped}[/green] Markdown document(s) are already indexed and up-to-date in ChromaDB.")
                elif docs:
                    index = get_index()
                    batch_size = 50
                    with GracefulInterrupt() as gi:
                        for i in range(0, len(docs), batch_size):
                            batch = docs[i : i + batch_size]
                            index.insert_nodes(batch)
                            summary["markdown_documents"] += len(batch)
                            if gi.interrupted:
                                break
                    skipped_text = f" ([dim]{skipped} up-to-date skipped[/dim])" if skipped > 0 else ""
                    console.print(f"  💾 Stored [green]{len(docs)}[/green] Markdown chunk(s){skipped_text} in vector DB")
            except KeyboardInterrupt:
                console.print("  [yellow]⚠ Markdown ingestion interrupted safely.[/yellow]")
            except Exception as e:
                console.print(f"  [yellow]Warning:[/yellow] Markdown ingestion encountered an issue: {e}")
            step += 1

    # 4. Ingest Staged Repositories
    repos_candidates = [root_p / "repos", root_p / "sources" / "repos"]
    repos_dirs = [d for d in repos_candidates if d.is_dir()]
    if repos_dirs:
        primary_repos_dir = repos_dirs[0]
        repo_subdirs = [d for d in primary_repos_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        if repo_subdirs:
            console.print(
                f"[bold cyan][{step}][/bold cyan] Ingesting {len(repo_subdirs)} staged repository(s) from [bold]{primary_repos_dir}[/bold]...")
            for rdir in repo_subdirs:
                # Ingest code AST
                console.print(f"  -> Ingesting source code AST for [bold]{rdir.name}[/bold]...")
                try:
                    res = ingest_code([rdir], force=force)
                    cdocs, skipped = res if isinstance(res, tuple) else (res, 0)
                    if skipped > 0 and not cdocs:
                        console.print(f"  ✨ All [green]{skipped}[/green] source file(s) for [bold]{rdir.name}[/bold] are already indexed and up-to-date in ChromaDB.")
                    elif cdocs:
                        index = get_index()
                        batch_size = 50
                        with GracefulInterrupt() as gi:
                            for i in range(0, len(cdocs), batch_size):
                                batch = cdocs[i : i + batch_size]
                                index.insert_nodes(batch)
                                summary["code_documents"] += len(batch)
                                if gi.interrupted:
                                    break
                        skipped_text = f" ([dim]{skipped} up-to-date skipped[/dim])" if skipped > 0 else ""
                        console.print(f"  💾 Stored [green]{len(cdocs)}[/green] code chunk(s){skipped_text} in vector DB")
                except KeyboardInterrupt:
                    console.print(f"  [yellow]⚠ Code AST ingestion for {rdir.name} interrupted safely.[/yellow]")
                    break
                except Exception as e:
                    console.print(f"  [yellow]Warning:[/yellow] Code AST ingestion failed for {rdir.name}: {e}")

                # Ingest git history if .git is present
                if (rdir / ".git").is_dir():
                    r_cfg = manifest_repo_configs.get(rdir.name, {})
                    repo_all_commits = all_commits or r_cfg.get("all_commits", False)
                    repo_max_commits = 0 if repo_all_commits else r_cfg.get("max_commits", 2000)

                    scope_desc = "all commits" if repo_all_commits else f"latest {repo_max_commits} commits"
                    console.print(f"  -> Ingesting Git commit history for [bold]{rdir.name}[/bold] ({scope_desc})...")
                    try:
                        with GracefulInterrupt():
                            new_commits, skipped_commits = ingest_git(
                                str(rdir),
                                max_commits=repo_max_commits,
                                all_commits=repo_all_commits,
                                force=force,
                            )
                        summary["git_commits"] += new_commits
                    except KeyboardInterrupt:
                        console.print(f"  [yellow]⚠ Git ingestion for {rdir.name} interrupted safely.[/yellow]")
                        break
                    except Exception as e:
                        console.print(f"  [yellow]Warning:[/yellow] Git commit ingestion failed for {rdir.name}: {e}")
            step += 1

    # 5. Ingest Jira Tickets (from manifests/jira.txt)
    jira_manifest = _find_manifest(root_p, "jira.txt")
    if jira_manifest:
        console.print(f"[bold cyan][{step}][/bold cyan] Ingesting Jira tickets declared in [bold]{jira_manifest}[/bold]...")
        with open(jira_manifest, "r", encoding="utf-8") as f:
            for line in f:
                clean = line.strip()
                if not clean or clean.startswith("#"):
                    continue

                # Parse: [server] "JQL" or just JQL
                server = None
                jql = clean
                parts = shlex.split(clean)
                if len(parts) >= 2 and not parts[0].startswith("project"):
                    server = parts[0]
                    jql = parts[1]
                elif len(parts) == 1:
                    jql = parts[0]

                console.print(f"  -> Fetching Jira issues: [dim]{jql}[/dim] (server: {server or 'default'})...")
                try:
                    count = ingest_jira(jql=jql, server=server, force=force)
                    summary["jira_tickets"] += count
                except Exception as e:
                    console.print(f"  [yellow]Warning:[/yellow] Jira ingestion failed for '{jql}': {e}")
        step += 1

    # 6. Ingest GitHub Issues & PRs (from manifests/github.txt)
    github_manifest = _find_manifest(root_p, "github.txt")
    if github_manifest:
        console.print(f"[bold cyan][{step}][/bold cyan] Ingesting GitHub Issues & PRs declared in [bold]{github_manifest}[/bold]...")
        with open(github_manifest, "r", encoding="utf-8") as f:
            for line in f:
                clean = line.strip()
                if not clean or clean.startswith("#"):
                    continue

                parts = clean.split()
                owner = parts[0]
                repo = parts[1] if len(parts) > 1 else ""
                state = parts[2] if len(parts) > 2 else "all"
                server = parts[3] if len(parts) > 3 else None

                if owner and repo:
                    console.print(f"  -> Ingesting GitHub [bold]{owner}/{repo}[/bold] (state: {state})...")
                    try:
                        res = ingest_github(owner=owner, repo=repo, state=state, server=server, force=force)
                        total_items = res[0] if isinstance(res, tuple) else res
                        skipped = res[3] if isinstance(res, tuple) and len(res) >= 4 else 0
                        summary["github_items"] += total_items
                        if skipped > 0 and total_items == 0:
                            console.print(
                                f"  ✨ All [green]{skipped}[/green] GitHub item(s) are already indexed and up-to-date in ChromaDB.")
                        elif skipped > 0:
                            console.print(
                                f"  💾 Stored [green]{total_items}[/green] new/updated chunk(s) ([dim]{skipped} up-to-date skipped[/dim]).")
                    except Exception as e:
                        console.print(f"  [yellow]Warning:[/yellow] GitHub ingestion failed for {owner}/{repo}: {e}")
        step += 1

    # 7. Ingest Bitbucket PRs (from manifests/bitbucket.txt)
    bitbucket_manifest = _find_manifest(root_p, "bitbucket.txt")
    if bitbucket_manifest:
        console.print(f"[bold cyan][{step}][/bold cyan] Ingesting Bitbucket PRs declared in [bold]{bitbucket_manifest}[/bold]...")
        with open(bitbucket_manifest, "r", encoding="utf-8") as f:
            for line in f:
                clean = line.strip()
                if not clean or clean.startswith("#"):
                    continue

                parts = clean.split()
                project = parts[0]
                repo = parts[1] if len(parts) > 1 else ""
                state = parts[2] if len(parts) > 2 else "ALL"
                server = parts[3] if len(parts) > 3 else None

                if project and repo:
                    console.print(f"  -> Ingesting Bitbucket PRs for [bold]{project}/{repo}[/bold] (state: {state})...")
                    try:
                        res = ingest_bitbucket(project=project, repo=repo, state=state, server=server, force=force)
                        count = res[0] if isinstance(res, tuple) else res
                        skipped = res[1] if isinstance(res, tuple) and len(res) >= 2 else 0
                        summary["bitbucket_prs"] += count
                        if skipped > 0 and count == 0:
                            console.print(
                                f"  ✨ All [green]{skipped}[/green] Bitbucket PR(s) are already indexed and up-to-date in ChromaDB.")
                        elif skipped > 0:
                            console.print(
                                f"  💾 Stored [green]{count}[/green] new/updated chunk(s) ([dim]{skipped} up-to-date skipped[/dim]).")
                    except Exception as e:
                        console.print(f"  [yellow]Warning:[/yellow] Bitbucket ingestion failed for {project}/{repo}: {e}")
        step += 1

    return summary
