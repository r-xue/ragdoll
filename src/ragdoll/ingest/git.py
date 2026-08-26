"""Git commit history ingestion module with incremental change detection."""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path

from llama_index.core import Document
from ragdoll.config import settings
from ragdoll.store.vectordb import _get_client, get_index

logger = logging.getLogger(__name__)

RECORD_SEP = chr(30)  # \x1e
UNIT_SEP = chr(31)    # \x1f


def ingest_git(
    repo_path: str | Path,
    max_commits: int = 2000,
    all_commits: bool = False,
    no_merges: bool = False,
    force: bool = False,
) -> tuple[int, int]:
    """Ingest git commit history into the vector store with incremental skipping.

    Args:
        repo_path (str | Path): Path to the local git repository.
        max_commits (int): Maximum number of commits to fetch (0 or negative for unlimited). Default 2000.
        all_commits (bool): If True, ignores max_commits and fetches full repository history.
        no_merges (bool): If True, excludes merge commits (--no-merges).
        force (bool): If True, re-indexes all commits even if already present in ChromaDB.

    Returns:
        tuple[int, int]: (newly_ingested_count, skipped_existing_count)
    """
    path = Path(repo_path).resolve()
    if not (path / ".git").exists() and not (
        path.is_file() and path.read_text(encoding="utf-8", errors="replace").startswith("gitdir:")
    ):
        logger.error("Not a valid git repository: %s", repo_path)
        return (0, 0)

    repo_name = path.name

    # Build git log command
    # Format: Hash (H), Parents (P), Ref Names (D), Author Name (an), Author Date ISO (aI), Subject (s), Body (b)
    format_str = "%H%x1f%P%x1f%D%x1f%an%x1f%aI%x1f%s%x1f%b%x1e"
    cmd = ["git", "-C", str(path), "log", "--all", f"--pretty=format:{format_str}"]

    if no_merges:
        cmd.append("--no-merges")

    if not all_commits and max_commits > 0:
        cmd.append(f"-n{max_commits}")

    logger.info(
        "Executing git log in %s (all_commits=%s, max=%s, no_merges=%s)...",
        path,
        all_commits or (max_commits <= 0),
        max_commits,
        no_merges,
    )

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        logger.error("Failed to run git log: %s", e.stderr)
        return (0, 0)

    raw_output = result.stdout
    if not raw_output:
        logger.info("No git commits found.")
        return (0, 0)

    commits = raw_output.split(RECORD_SEP)

    # Connect to ChromaDB for fast incremental ID lookup
    client = _get_client()
    chroma_col = client.get_or_create_collection(settings.collection_name)

    candidate_docs: list[Document] = []
    doc_ids: list[str] = []

    for commit_data in commits:
        commit_data = commit_data.strip()
        if not commit_data:
            continue

        parts = commit_data.split(UNIT_SEP)
        if len(parts) < 6:
            continue

        commit_hash = parts[0]
        parents = parts[1]
        refs = parts[2]
        author = parts[3]
        date_iso = parts[4]
        subject = parts[5]
        body = parts[6] if len(parts) > 6 else ""

        try:
            dt = datetime.fromisoformat(date_iso)
            ts = dt.timestamp()
        except Exception:
            ts = 0.0

        text_blocks = [f"Commit: {commit_hash}"]
        if parents:
            text_blocks.append(f"Parents: {parents}")
        if refs:
            text_blocks.append(f"Branches/Tags: {refs}")

        text_blocks.extend([
            f"Author: {author}",
            f"Date: {date_iso}",
            "",
            subject,
            "",
            body,
        ])

        text = chr(10).join(text_blocks)
        doc_id = f"git-{repo_name}-{commit_hash}"

        metadata = {
            "source": "git",
            "repo_name": repo_name,
            "repo_path": str(path),
            "commit_hash": commit_hash,
            "parents": parents,
            "refs": refs,
            "author": author,
            "subject": subject,
            "created_at_ts": ts,
        }

        doc = Document(text=text, metadata=metadata)
        doc.id_ = doc_id
        candidate_docs.append(doc)
        doc_ids.append(doc_id)

    total_scanned = len(candidate_docs)
    if total_scanned == 0:
        return (0, 0)

    # Bulk query ChromaDB for existing commit IDs to skip redundant embeddings
    existing_ids = set()
    if not force:
        # Query ChromaDB in batches of 1000 IDs to avoid query limits
        batch_size = 1000
        for i in range(0, len(doc_ids), batch_size):
            chunk_ids = doc_ids[i: i + batch_size]
            try:
                records = chroma_col.get(ids=chunk_ids, include=[])
                if records and records.get("ids"):
                    existing_ids.update(records["ids"])
            except Exception as e:
                logger.debug("ChromaDB ID lookup notice: %s", e)

    new_docs = [doc for doc in candidate_docs if doc.id_ not in existing_ids]
    skipped_count = len(existing_ids)

    logger.info(
        "Scanned %d commit(s): %d new to index, %d already up-to-date in ChromaDB.",
        total_scanned,
        len(new_docs),
        skipped_count,
    )

    if not new_docs:
        return (0, skipped_count)

    from rich.progress import (
        Progress,
        TextColumn,
        BarColumn,
        TaskProgressColumn,
        MofNCompleteColumn,
        TimeRemainingColumn,
    )
    from rich.console import Console
    from ragdoll.store.safety import GracefulInterrupt

    console = Console()
    index = get_index()
    batch_embed_size = 64
    batch_ranges = list(range(0, len(new_docs), batch_embed_size))

    with GracefulInterrupt() as gi, Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=35),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Embedding git commits...", total=len(new_docs))
        for i in batch_ranges:
            batch_docs = new_docs[i : i + batch_embed_size]
            index.insert_nodes(batch_docs)
            progress.advance(task, advance=len(batch_docs))
            if gi.interrupted:
                break

    logger.info("Successfully indexed %d new git commits.", len(new_docs))
    return (len(new_docs), skipped_count)
