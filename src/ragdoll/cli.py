"""Ragdoll CLI — the main user-facing entry point.

Provides commands for ingesting data, searching, summarizing, and
interacting with the local RAG system.

Usage::

    ragdoll ingest pdf ./docs/
    ragdoll ingest jira --jql "project = CAS AND updated >= -30d"
    ragdoll search "tclean performance regression"
    ragdoll summarize "AsdmStMan known issues"
    ragdoll chat
    ragdoll status
"""

from __future__ import annotations

import logging
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from ragdoll import __version__
from ragdoll.config import settings

console = Console()
logger = logging.getLogger(__name__)

# ── Logging setup ──────────────────────────────────────────────────────


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, console=console)],
    )
    # Hide HTTP request spam from ollama/httpx which interferes with the progress bar
    if not verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)


# ── CLI root ───────────────────────────────────────────────────────────

@click.group()
@click.version_option(__version__, prog_name="ragdoll")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def cli(verbose: bool) -> None:
    """🧶 Ragdoll — local RAG over JIRA tickets & PDF documents."""
    import faulthandler
    faulthandler.enable()
    _setup_logging(verbose)


# ── Ingest command group ───────────────────────────────────────────────

@cli.group()
def ingest() -> None:
    """Ingest data sources into the vector store."""


@ingest.command("pdf")
@click.argument("paths", nargs=-1, type=click.Path(exists=True))
@click.option("--force", is_flag=True, default=False, help="Force re-indexing of all PDFs even if unmodified.")
def ingest_pdf(paths: tuple[str, ...], force: bool) -> None:
    """Ingest PDF files or directories of PDFs with incremental change detection."""
    from ragdoll.ingest.pdf import ingest_pdfs
    from ragdoll.store.vectordb import count

    if not paths:
        console.print("[red]Error:[/red] Provide at least one PDF file or directory.")
        raise SystemExit(1)

    console.print(f"[bold cyan]Scanning and embedding PDFs from {paths[0]}…[/bold cyan]")
    new_count, skipped_count = ingest_pdfs(list(paths), force=force)

    if new_count == 0 and skipped_count == 0:
        console.print("[yellow]No PDF documents found or extracted.[/yellow]")
        return

    if new_count > 0:
        skip_str = f" ([dim]{skipped_count} already up-to-date skipped[/dim])" if skipped_count > 0 else ""
        console.print(f"  � Stored [green]{new_count}[/green] new/updated chunk(s){skip_str} in vector DB")
    else:
        console.print(f"  ✨ All [green]{skipped_count}[/green] PDF(s) are already indexed and up-to-date in ChromaDB.")

    console.print(f"  📊 Total chunks in collection: [bold]{count()}[/bold]")


@ingest.command("jira")
@click.option("--jql", required=True, help="JQL query to fetch issues.")
@click.option("--max-results", type=int, default=None, help="Max issues to fetch.")
@click.option("--url", default=None, help="JIRA server URL (overrides config).")
@click.option("--user", default=None, help="JIRA username (overrides config).")
@click.option("--token", default=None, help="JIRA API token / PAT (overrides config).")
@click.option("--auth-method", type=click.Choice(["pat", "basic"]), default=None, help="Auth method (overrides config).")
@click.option("--server", type=str, default=None, help="Name of the Jira server config to use.")
@click.option("--chunk-size", type=int, default=None, help="Override chunk size.")
@click.option("-f", "--force", is_flag=True, help="Force re-indexing of all issues even if unchanged.")
@click.option("--chunk-overlap", type=int, default=None, help="Override chunk overlap.")
def ingest_jira(
    jql: str,
    server: str | None,
    max_results: int | None,
    force: bool,
    url: str | None,
    user: str | None,
    token: str | None,
    auth_method: str | None,
    chunk_size: int | None,
    chunk_overlap: int | None,
) -> None:
    """Ingest JIRA issues matching a JQL query.

    For multi-site ingestion, use --server to reference a pre-configured server 
    in your config.toml, or use --url and --token to override manually.
    """
    from ragdoll.ingest.jira import ingest_jira as _ingest_jira
    from ragdoll.store.vectordb import count

    n = _ingest_jira(
        jql=jql,
        server=server,
        max_results=max_results,
        force=force,
        override_url=url,
        override_user=user,
        override_token=token,
        override_auth_method=auth_method
    )

    if n == 0:
        console.print("[yellow]No issues found or ingested for the given JQL.[/yellow]")
        return

    console.print(f"  💾 Stored [green]{n}[/green] chunk(s) in vector DB")
    console.print(f"  📊 Total chunks in collection: [bold]{count()}[/bold]")


@ingest.command("bitbucket")
@click.option("--project", required=True, help="Bitbucket project key.")
@click.option("--repo", required=True, help="Bitbucket repository slug.")
@click.option("--state", default="ALL", type=click.Choice(["ALL", "OPEN", "MERGED", "DECLINED"]), help="PR state to filter.")
@click.option("--server", type=str, default=None, help="Name of the Bitbucket server config to use.")
@click.option("--url", default=None, help="Bitbucket server URL (overrides config).")
@click.option("--user", default=None, help="Username (overrides config).")
@click.option("--token", default=None, help="API token / PAT (overrides config).")
@click.option("--auth-method", type=click.Choice(["pat", "basic"]), default=None, help="Auth method (overrides config).")
def ingest_bitbucket_cmd(
    project: str,
    repo: str,
    state: str,
    server: str | None,
    url: str | None,
    user: str | None,
    token: str | None,
    auth_method: str | None,
) -> None:
    """Ingest Bitbucket Server PRs and comments."""
    from ragdoll.ingest.bitbucket import ingest_bitbucket as _ingest_bitbucket
    from ragdoll.store.vectordb import count

    with console.status(f"[bold cyan]Fetching and embedding Bitbucket PRs from {project}/{repo}…"):
        n = _ingest_bitbucket(
            project=project,
            repo=repo,
            state=state,
            server=server,
            override_url=url,
            override_user=user,
            override_token=token,
            override_auth_method=auth_method
        )

    if n == 0:
        console.print("[yellow]No PRs found or ingested.[/yellow]")
        return

    console.print(f"  💾 Stored [green]{n}[/green] chunk(s) in vector DB")
    console.print(f"  📊 Total chunks in collection: [bold]{count()}[/bold]")


@ingest.command("github")
@click.argument("owner")
@click.argument("repo")
@click.option("--state", default="all", help="Issue state (all, open, closed).")
@click.option("--server", default=None, help="Server config to use from settings.")
@click.option("--url", default=None, help="Override GitHub API URL.")
@click.option("--token", default=None, help="Override GitHub Personal Access Token.")
def ingest_github_cmd(
    owner: str,
    repo: str,
    state: str,
    server: str | None,
    url: str | None,
    token: str | None,
) -> None:
    """Ingest GitHub Issues and PRs (with comments)."""
    from ragdoll.ingest.github import ingest_github as _ingest_github
    from ragdoll.store.vectordb import count

    with console.status(f"[bold cyan]Fetching and embedding GitHub Issues/PRs from {owner}/{repo}…"):
        n, num_issues, num_prs = _ingest_github(
            owner=owner,
            repo=repo,
            state=state,
            server=server,
            override_url=url,
            override_token=token,
        )

    if n == 0:
        console.print("[yellow]No Issues or PRs found or ingested.[/yellow]")
        return

    console.print(
        f"  💾 Stored [green]{n}[/green] chunk(s) ([cyan]{num_issues}[/cyan] Issues, [cyan]{num_prs}[/cyan] Pull Requests) in vector DB")
    console.print(f"  📊 Total chunks in collection: [bold]{count()}[/bold]")


@ingest.command("code")
@click.argument("paths", nargs=-1, type=click.Path(exists=True))
@click.option("--ext", default=None, help="Comma-separated extensions to filter (e.g. .py,.cpp,.h,.xml).")
@click.option("--chunk-size", type=int, default=None, help="Override chunk size.")
@click.option("--chunk-overlap", type=int, default=None, help="Override chunk overlap.")
def ingest_code(
    paths: tuple[str, ...],
    ext: str | None,
    chunk_size: int | None,
    chunk_overlap: int | None,
) -> None:
    """Ingest source code files or repositories (Python, C/C++, Fortran, Shell, etc.)."""
    import collections
    from ragdoll.ingest.code import ingest_code as _ingest_code
    from ragdoll.store.vectordb import count, get_index

    if not paths:
        console.print("[red]Error:[/red] Provide at least one source file or directory.")
        raise SystemExit(1)

    code_paths = [Path(p) for p in paths]
    ext_set = None
    if ext:
        ext_set = {f".{e.strip().lstrip(".").lower()}" for e in ext.split(",") if e.strip()}

    with console.status("[bold cyan]Parsing source files across supported languages…"):
        docs = _ingest_code(
            code_paths,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            extensions=ext_set,
        )

    if not docs:
        console.print("[yellow]No source code documents extracted.[/yellow]")
        return

    lang_counts = collections.Counter(d.metadata.get("language", "generic") for d in docs)
    lang_summary = ", ".join(f"{lang}: {cnt}" for lang, cnt in lang_counts.most_common(5))

    console.print(f"  📦 Extracted [green]{len(docs)}[/green] code unit(s) ({lang_summary})")

    from rich.progress import track
    console.print("\n[bold cyan]Embedding and storing chunks into ChromaDB…[/bold cyan]")
    index = get_index()
    for doc in track(docs, description="Embedding code...", console=console):
        index.insert(doc)
    n = len(docs)

    console.print(f"  💾 Stored [green]{n}[/green] document node(s) in vector DB")
    console.print(f"  📊 Total chunks in collection: [bold]{count()}[/bold]")


@ingest.command("git")
@click.argument("repo_path", type=click.Path(exists=True))
@click.option("--max-commits", type=int, default=2000, help="Max commits to fetch (0 for full history). Default: 2000.")
@click.option("--all", "all_commits", is_flag=True, default=False, help="Ingest all commits (full repository history).")
@click.option("--no-merges", is_flag=True, default=False, help="Exclude merge commits from ingestion.")
@click.option("-f", "--force", is_flag=True, default=False, help="Force re-indexing of all matching commits.")
def ingest_git_cmd(repo_path: str, max_commits: int, all_commits: bool, no_merges: bool, force: bool) -> None:
    """Ingest git commit history from a local repository with incremental skipping."""
    from ragdoll.ingest.git import ingest_git as _ingest_git
    from ragdoll.store.vectordb import count

    console.print(f"[bold cyan]Scanning git commits from {repo_path}…[/bold cyan]")
    new_count, skipped_count = _ingest_git(
        repo_path=repo_path,
        max_commits=max_commits,
        all_commits=all_commits,
        no_merges=no_merges,
        force=force,
    )

    if new_count == 0 and skipped_count == 0:
        console.print("[yellow]No commits found.[/yellow]")
        return

    if new_count > 0:
        skip_str = f" ([dim]{skipped_count} already up-to-date skipped[/dim])" if skipped_count > 0 else ""
        console.print(f"  💾 Stored [green]{new_count}[/green] new commit(s){skip_str} in vector DB")
    else:
        console.print(f"  ✨ All [green]{skipped_count}[/green] commits are already indexed and up-to-date in ChromaDB.")

    console.print(f"  📊 Total chunks in collection: [bold]{count()}[/bold]")


@ingest.command("all")
@click.argument("path", type=click.Path(exists=False, file_okay=False, path_type=Path), default=None, required=False)
@click.option("--clone/--no-clone", default=False, help="Clone/update repositories listed in repos/repos.txt before ingesting.")
@click.option("-f", "--force", is_flag=True, default=False, help="Force re-indexing of all data sources even if unchanged.")
@click.option("-a", "--all-commits", is_flag=True, default=False, help="Index full git history for all repositories (ignores commit count limits).")
def ingest_all_cmd(path: Path | None, clone: bool, force: bool, all_commits: bool) -> None:
    """Recursively ingest all PDF documents, Markdown specs, and staged code repositories."""
    from ragdoll.ingest.staging import ingest_all_sources, get_working_dir

    work_dir = get_working_dir()
    if path is None or str(path) in (".", "sources"):
        if (work_dir / "manifests").is_dir() or (work_dir / "pdf").is_dir() or (work_dir / "sources").is_dir():
            target_path = work_dir
        else:
            target_path = Path("sources").resolve()
    else:
        target_path = Path(path)
        if not target_path.is_absolute():
            target_path = (work_dir / target_path).resolve()

    console.print(
        Panel(
            f"🧶 [bold cyan]Ragdoll Knowledge Ingestion[/bold cyan]\n"
            f"Root Directory: [bold]{target_path}[/bold]\n"
            f"Auto-stage Repositories: [bold]{clone}[/bold]\n"
            f"Force Re-index: [bold]{force}[/bold]\n"
            f"All Commits History: [bold]{all_commits}[/bold]",
            expand=False,
        )
    )
    try:
        summary = ingest_all_sources(root_path=target_path, clone_first=clone, force=force, all_commits=all_commits)
    except Exception as e:
        logger.exception("Ingestion failed: %s", e)
        console.print(f"[bold red]Ingestion Error:[/bold red] {e}")
        raise click.Abort()

    table = Table(title="Ingestion Summary", show_header=True, header_style="bold cyan")
    table.add_column("Category", style="bold")
    table.add_column("Ingested Count", justify="right")

    table.add_row("PDF Document Pages / Nodes", str(summary["pdf_documents"]))
    table.add_row("Markdown Specification Chunks", str(summary["markdown_documents"]))
    table.add_row("Source Code AST Chunks", str(summary["code_documents"]))
    table.add_row("Git Commits Indexed", str(summary["git_commits"]))
    if summary.get("jira_tickets", 0) > 0:
        table.add_row("Jira Tickets & Comments", str(summary["jira_tickets"]))
    if summary.get("github_items", 0) > 0:
        table.add_row("GitHub Issues & PRs", str(summary["github_items"]))
    if summary.get("bitbucket_prs", 0) > 0:
        table.add_row("Bitbucket PR Discussions", str(summary["bitbucket_prs"]))

    console.print(table)
    console.print("\n✨ [bold green]Ingestion complete![/bold green] Start chatting with: [bold]pixi run ragdoll chat[/bold]")


@cli.command("stage-repos")
@click.argument("manifest", type=click.Path(dir_okay=False, path_type=Path), required=False)
@click.option("--target-dir", "-d", type=click.Path(file_okay=False, path_type=Path), default=None, help="Target directory to clone repositories into.")
@click.option("--pull/--no-pull", default=True, help="Update existing repositories with git pull --ff-only.")
@click.option("--depth", type=int, default=None, help="Create shallow clone with specified commit depth.")
def stage_repos_cmd(manifest: Path | None, target_dir: Path | None, pull: bool, depth: int | None) -> None:
    """Clone or update external Git repositories listed in a manifest file (e.g. repos.txt)."""
    from ragdoll.ingest.staging import stage_repositories
    try:
        results = stage_repositories(manifest_path=manifest, target_dir=target_dir, pull=pull, depth=depth)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()

    table = Table(title="Staged Repositories", show_header=True, header_style="bold cyan")
    table.add_column("Repository", style="bold")
    table.add_column("Branch")
    table.add_column("Destination")
    table.add_column("Status")

    for r in results:
        style = "green" if r["status"] in ("Cloned", "Updated", "Up to date") else "yellow" if "Skipped" in r["status"] else "red"
        status_str = f"[{style}]{r['status']}[/{style}]"
        if r["error"]:
            status_str += f" ({r['error']})"
        table.add_row(r["name"], r["branch"], str(r["path"]), status_str)

    console.print(table)


@cli.command("stage-pdfs")
@click.argument("manifest", type=click.Path(dir_okay=False, path_type=Path), required=False)
@click.option("--target-dir", "-d", type=click.Path(file_okay=False, path_type=Path), default=None, help="Target directory to download PDFs into.")
@click.option("--force", "-f", is_flag=True, default=False, help="Force re-downloading PDFs even if they already exist locally.")
def stage_pdfs_cmd(manifest: Path | None, target_dir: Path | None, force: bool) -> None:
    """Download and sync remote PDF documents declared in a manifest file (e.g. pdf.txt)."""
    from ragdoll.ingest.staging import stage_pdfs
    try:
        results = stage_pdfs(manifest_path=manifest, target_dir=target_dir, force=force)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()

    table = Table(title="Staged PDF Documents", show_header=True, header_style="bold cyan")
    table.add_column("Document / URL", style="cyan")
    table.add_column("Destination", style="dim")
    table.add_column("Status")

    for r in results:
        style = "green" if r["status"] in ("Downloaded", "Up to date") else "red"
        status_str = f"[{style}]{r["status"]}[/{style}]"
        if r.get("error"):
            status_str += f" ({r["error"]})"
        table.add_row(r["url"], str(r["destination"]), status_str)

    console.print(table)


# Direct CLI root alias for ingest-all
cli.add_command(ingest_all_cmd, name="ingest-all")


# ── Search command ─────────────────────────────────────────────────────

@cli.command()
@click.argument("query")
@click.option("-n", "--top-k", type=int, default=None, help="Number of results.")
@click.option("--source", type=click.Choice(["pdf", "jira", "bitbucket", "github", "code", "git"]), default=None, help="Filter by source.")
def search(query: str, top_k: int | None, source: str | None) -> None:
    """Semantic search over ingested documents."""
    from ragdoll.query.retriever import search as _search

    with console.status("[bold cyan]Searching…"):
        results = _search(query, top_k=top_k, source_filter=source)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"Search Results for: {query!r}", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Source", style="cyan", width=20)
    table.add_column("Score", style="green", width=8)
    table.add_column("Text", ratio=1)

    for i, r in enumerate(results, 1):
        source_id = r.metadata.get("doc_id", r.chunk_id)
        # Truncate text for table display.
        text_preview = r.text[:300] + "…" if len(r.text) > 300 else r.text
        table.add_row(str(i), source_id, f"{r.score:.4f}", text_preview)

    console.print(table)


# ── Summarize command ──────────────────────────────────────────────────

@cli.command()
@click.argument("topic")
@click.option("-n", "--top-k", type=int, default=None, help="Number of context chunks.")
@click.option("--source", type=click.Choice(["pdf", "jira", "bitbucket", "github", "code", "git"]), default=None, help="Filter by source.")
def summarize(topic: str, top_k: int | None, source: str | None) -> None:
    """Summarize information about a topic from ingested data."""
    from ragdoll.query.rag import summarize as _summarize

    console.print(f"\n[bold cyan]Summarizing:[/bold cyan] {topic}\n")

    response = _summarize(topic, top_k=top_k, source_filter=source, stream=True)

    full_text = ""
    for token in response:
        full_text += token
        console.print(token, end="")

    console.print()  # newline
    console.print()


# ── Chat command ───────────────────────────────────────────────────────

@cli.command()
@click.option("--source", type=click.Choice(["pdf", "jira", "bitbucket", "github", "code", "git"]), default=None, help="Filter context by source.")
@click.option("-n", "--top-k", type=int, default=None, help="Number of context chunks per turn.")
@click.option("--think/--no-think", "enable_thinking", default=None, help="Enable or disable model thinking/reasoning mode.")
def chat(source: str | None, top_k: int | None, enable_thinking: bool | None = None) -> None:
    """Interactive RAG chat session.

    Type your questions and get answers grounded in your ingested data.
    Type 'quit', 'exit', or Ctrl+C to end the session.
    """
    from ragdoll.config import settings
    from ragdoll.query.rag import chat_with_context

    effective_top_k = top_k or settings.top_k
    effective_thinking = settings.enable_thinking if enable_thinking is None else enable_thinking
    thinking_str = "Enabled (Deep)" if effective_thinking else "Disabled (Fast)"
    source_info = f" [dim](Filtered: [bold]{source}[/bold])[/dim]" if source else ""

    if settings.chroma_host:
        vector_info = f"Remote ChromaDB ({settings.chroma_host}:{settings.chroma_port})"
    else:
        vector_info = "Local ChromaDB"

    spec_text = (
        "[bold cyan]🧶 Ragdoll Interactive Chat[/bold cyan]\n\n"
        "Ask questions across your ingested codebase, technical documentation, and live APIs.\n\n"
        f"[dim]•[/dim] [bold]LLM (Chat Model):[/bold]        [green]{settings.chat_model}[/green]\n"
        f"[dim]•[/dim] [bold]Thinking Mode:[/bold]           [cyan]{thinking_str}[/cyan]\n"
        f"[dim]•[/dim] [bold]Embedding Model:[/bold]         [green]{settings.embed_model}[/green]\n"
        f"[dim]•[/dim] [bold]Vector Store:[/bold]            [cyan]{vector_info}[/cyan]\n"
        f"[dim]•[/dim] [bold]Retrieval Depth:[/bold]         [cyan]Top-K {effective_top_k} chunks[/cyan]{source_info}\n\n"
        "Type [bold]quit[/bold] or [bold]exit[/bold] to end the session."
    )

    console.print(
        Panel(
            spec_text,
            title="Interactive RAG Chat",
            border_style="cyan",
        )
    )

    try:
        import readline
    except ImportError:
        readline = None  # type: ignore[assignment]

    # ── Persistent input history ──────────────────────────────────────
    history_file = Path.home() / ".ragdoll" / "chat_history"
    if readline is not None:
        history_file.parent.mkdir(parents=True, exist_ok=True)
        readline.set_history_length(500)
        try:
            readline.read_history_file(str(history_file))
        except Exception:
            pass  # corrupt or missing history — continue cleanly

    def _save_history() -> None:
        if readline is not None:
            try:
                readline.write_history_file(str(history_file))
            except OSError:
                pass

    messages: list[dict[str, str]] = []

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            _save_history()
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            _save_history()
            console.print("[dim]Goodbye![/dim]")
            break

        messages.append({"role": "user", "content": user_input})

        console.print("\n[bold cyan]Ragdoll:[/bold cyan] ", end="")

        try:
            response = chat_with_context(
                messages,
                top_k=top_k,
                source_filter=source,
                stream=True,
                enable_thinking=effective_thinking,
            )

            full_response = ""
            for token in response:
                full_response += token
                console.print(token, end="")

            console.print()  # newline
            messages.append({"role": "assistant", "content": full_response})

        except Exception as e:
            err_str = str(e)
            if "connection refused" in err_str.lower() or "connecterror" in err_str.lower() or "failed to establish a new connection" in err_str.lower():
                console.print(
                    f"\n[bold red]Connection Error:[/bold red] Could not connect to Ollama service at [cyan]{settings.ollama_host}[/cyan].\n"
                    "[dim]👉 Hint: Is Ollama running? Try running [bold]ollama serve[/bold] or check [bold]systemctl status ollama[/bold][/dim]"
                )
            elif "not found" in err_str.lower() and (settings.chat_model in err_str or "model" in err_str.lower()):
                console.print(
                    f"\n[bold red]Model Error:[/bold red] LLM model [cyan]{settings.chat_model}[/cyan] is not installed or available in Ollama.\n"
                    f"[dim]👉 Hint: Run [bold]ollama pull {settings.chat_model}[/bold] in your terminal to install it.[/dim]"
                )
            else:
                console.print(f"\n[red]Error: {e}[/red]")
            # Remove the failed user message to keep history clean.
            messages.pop()


# ── Web UI & API ───────────────────────────────────────────────────────

@cli.command()
@click.option("--port", type=int, default=7860, help="Port to run the UI on.")
def ui(port: int) -> None:
    """Launch the built-in Gradio web interface."""
    try:
        from ragdoll.ui import launch_ui
        launch_ui(port=port)
    except ImportError:
        console.print("[bold red]Error:[/bold red] Gradio is not installed. Run [cyan]pixi add gradio[/cyan] first.")
        import sys
        sys.exit(1)


@cli.command()
@click.option("--host", type=str, default="0.0.0.0", help="Host to bind the server to.")
@click.option("--port", type=int, default=8000, help="Port to run the server on.")
def serve(host: str, port: int) -> None:
    """Start an OpenAI-compatible REST API for Open WebUI integration."""
    try:
        from ragdoll.api import run_server
        console.print(f"[bold green]Starting Ragdoll API on {host}:{port}[/bold green]")
        run_server(host=host, port=port)
    except ImportError:
        console.print("[bold red]Error:[/bold red] FastAPI is not installed. Run [cyan]pixi add fastapi uvicorn[/cyan] first.")
        import sys
        sys.exit(1)


@cli.command()
@click.option("--transport", type=click.Choice(["stdio", "sse"]), default="stdio", help="Transport protocol to use (stdio for local, sse for network).")
@click.option("--port", type=int, default=8000, help="Port to run the SSE server on (only used if transport=sse).")
def mcp(transport: str, port: int) -> None:
    """Start the Model Context Protocol (MCP) server for Ragdoll."""
    try:
        from ragdoll.mcp import main as run_mcp
        if transport == "sse":
            console.print(f"[bold green]Starting Ragdoll MCP Server via SSE on port {port}[/bold green]")
        run_mcp(transport=transport, port=port)
    except ImportError:
        console.print("[bold red]Error:[/bold red] mcp package is not installed.")
        import sys
        sys.exit(1)


# ── Status command ─────────────────────────────────────────────────────

@cli.command("serve-chroma")
@click.option("--host", default="0.0.0.0", help="Host to bind the Chroma server to. Default: 0.0.0.0")
@click.option("--port", type=int, default=8000, help="Port to run the Chroma server on. Default: 8000")
@click.option("--path", "data_path", default=None, help="Path to persist ChromaDB data. Defaults to ~/.ragdoll/data/chroma")
def serve_chroma_cmd(host: str, port: int, data_path: str | None) -> None:
    """Launch a standalone ChromaDB HTTP vector server for team sharing."""
    import subprocess
    storage_path = data_path or str(settings.chroma_dir)
    Path(storage_path).mkdir(parents=True, exist_ok=True)
    console.print(f"[bold green]Starting ChromaDB server on {host}:{port}[/bold green]")
    console.print(f"  📁 Storage Directory: [cyan]{storage_path}[/cyan]")
    console.print("  Press [bold red]Ctrl+C[/bold red] to stop.\n")
    try:
        subprocess.run(["chroma", "run", "--host", host, "--port", str(port), "--path", storage_path], check=True)
    except KeyboardInterrupt:
        console.print("\n[dim]ChromaDB server stopped.[/dim]")
    except FileNotFoundError:
        console.print("[bold red]Error:[/bold red] 'chroma' CLI not found in PATH.")


@cli.command("clear")
@click.option("-f", "--force", is_flag=True, help="Skip confirmation prompt.")
def clear_cmd(force: bool) -> None:
    """Clear the ChromaDB vector database collection."""
    from ragdoll.store.vectordb import delete_collection

    current_count = None
    if not force:
        from ragdoll.store.safety import check_chromadb_health
        if check_chromadb_health():
            try:
                from ragdoll.store.vectordb import count
                current_count = count()
            except Exception:
                pass

        if current_count is not None and current_count == 0:
            console.print("[yellow]Vector store collection is already empty.[/yellow]")
            return

        count_label = f"{current_count} chunk(s)" if current_count is not None else "all data"
        confirm = click.confirm(
            f"Are you sure you want to delete {count_label} from collection '{settings.collection_name}'?",
            default=False,
        )
        if not confirm:
            console.print("[dim]Aborted.[/dim]")
            return
    else:
        count_label = "all data"

    try:
        delete_collection()
    except Exception as e:
        # If ChromaDB's Rust backend segfaults on delete, fall back to purging the storage dir
        logger.debug("delete_collection failed (%s), purging storage directory directly.", e)
        import shutil
        if settings.chroma_dir.exists():
            shutil.rmtree(settings.chroma_dir, ignore_errors=True)
            settings.ensure_dirs()
    console.print(f"[bold green]✓ Cleared {count_label} from collection '{settings.collection_name}'.[/bold green]")


@cli.command()
def status() -> None:
    """Show the current Ragdoll status: index stats, model info, config."""
    from ragdoll.llm.ollama import list_models
    from ragdoll.store.vectordb import count, list_collections

    console.print(Panel("[bold cyan]🧶 Ragdoll Status[/bold cyan]", border_style="cyan"))

    # Config summary.
    config_table = Table(title="Configuration", show_header=False)
    config_table.add_column("Key", style="dim")
    config_table.add_column("Value")
    config_table.add_row("Ollama host", settings.ollama_host)
    config_table.add_row("Embed model", settings.embed_model)
    config_table.add_row("Chat model", settings.chat_model)
    config_table.add_row("Data directory", str(settings.data_dir))
    config_table.add_row("Chunk size", str(settings.chunk_size))
    config_table.add_row("Chunk overlap", str(settings.chunk_overlap))
    config_table.add_row("Top-K", str(settings.top_k))
    if settings.chroma_host:
        config_table.add_row("ChromaDB mode", f"[green]Remote Server[/green] ({settings.chroma_host}:{settings.chroma_port})")
    else:
        config_table.add_row("ChromaDB mode", f"Local Embedded ({settings.chroma_dir})")
    console.print(config_table)

    # Vector store info.
    try:
        collections = list_collections()
        console.print(f"\n[bold]Vector Store:[/bold] {len(collections)} collection(s)")
        for name in collections:
            n = count(name)
            console.print(f"  • [cyan]{name}[/cyan]: {n} chunks")
    except Exception:
        console.print("  [yellow]Vector store not initialised yet.[/yellow]")

    # Ollama models.
    try:
        models = list_models()
        model_table = Table(title="\nOllama Models")
        model_table.add_column("Name", style="cyan")
        model_table.add_column("Size")
        model_table.add_column("Modified")
        for m in models:
            size_gb = m.get("size", 0) / 1e9
            model_table.add_row(
                m.get("name", "?"),
                f"{size_gb:.1f} GB",
                m.get("modified_at", "?")[:19],
            )
        console.print(model_table)
    except Exception as e:
        console.print(f"  [yellow]Cannot connect to Ollama: {e}[/yellow]")


# ── Entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
