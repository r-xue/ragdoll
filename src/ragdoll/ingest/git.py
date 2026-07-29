"""Git commit history ingestion module."""

import logging
import subprocess
from datetime import datetime
from pathlib import Path

from llama_index.core import Document
from ragdoll.store.vectordb import get_index

logger = logging.getLogger(__name__)

def ingest_git(repo_path: str, max_commits: int = 1000) -> int:
    """Ingest git commit history into the vector store.
    
    Args:
        repo_path (str): Path to the git repository.
        max_commits (int): Maximum number of commits to fetch.
        
    Returns:
        int: Number of commits ingested.
    """
    path = Path(repo_path)
    if not (path / ".git").exists() and not (path.is_file() and path.read_text(encoding="utf-8", errors="replace").startswith("gitdir:")):
        logger.error("Not a git repository: %s", repo_path)
        return 0

    # Format: Hash (H), Parents (P), Ref Names (D), Author Name (an), Author Date ISO (aI), Subject (s), Body (b)
    # Using \x1f (unit separator) to separate fields and \x1e (record separator) to separate commits.
    format_str = "%H%x1f%P%x1f%D%x1f%an%x1f%aI%x1f%s%x1f%b%x1e"
    cmd = ["git", "-C", str(repo_path), "log", "--all", f"-n{max_commits}", f"--pretty=format:{format_str}"]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        logger.error("Failed to run git log: %s", e.stderr)
        return 0
        
    raw_output = result.stdout
    if not raw_output:
        return 0
        
    commits = raw_output.split("\x1e")
    documents = []
    
    for commit_data in commits:
        commit_data = commit_data.strip()
        if not commit_data:
            continue
            
        parts = commit_data.split("\x1f")
        if len(parts) < 7:
            continue
            
        commit_hash = parts[0]
        parents = parts[1]
        refs = parts[2]
        author = parts[3]
        date_iso = parts[4]
        subject = parts[5]
        body = parts[6]
        
        # Convert date for metadata
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
            body
        ])
        
        text = "\n".join(text_blocks)
        
        metadata = {
            "source": "git",
            "repo_path": str(path.absolute()),
            "commit_hash": commit_hash,
            "parents": parents,
            "refs": refs,
            "author": author,
            "subject": subject,
            "created_at_ts": ts,
        }
        
        doc = Document(text=text, metadata=metadata)
        doc.id_ = f"git-{commit_hash}"
        documents.append(doc)
        
    if not documents:
        logger.info("No commits found to ingest.")
        return 0
        
    logger.info("Fetched %d git commits. Indexing into vector store...", len(documents))
    
    from rich.progress import track
    index = get_index()
    for doc in track(documents, description="Embedding git commits...", console=None):
        index.insert(doc)
        
    logger.info("Successfully ingested git commits.")
    return len(documents)
