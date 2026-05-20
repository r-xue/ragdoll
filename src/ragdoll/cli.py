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

# ── Logging setup ──────────────────────────────────────────────────────


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, console=console)],
    )


# ── CLI root ───────────────────────────────────────────────────────────

@click.group()
@click.version_option(__version__, prog_name="ragdoll")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def cli(verbose: bool) -> None:
    """🧶 Ragdoll — local RAG over JIRA tickets & PDF documents."""
    _setup_logging(verbose)


# ── Ingest command group ───────────────────────────────────────────────

@cli.group()
def ingest() -> None:
    """Ingest data sources into the vector store."""


@ingest.command("pdf")
@click.argument("paths", nargs=-1, type=click.Path(exists=True))
@click.option("--chunk-size", type=int, default=None, help="Override chunk size.")
@click.option("--chunk-overlap", type=int, default=None, help="Override chunk overlap.")
def ingest_pdf(paths: tuple[str, ...], chunk_size: int | None, chunk_overlap: int | None) -> None:
    """Ingest PDF files or directories of PDFs."""
    from ragdoll.ingest.chunker import chunk_documents
    from ragdoll.ingest.pdf import ingest_pdfs
    from ragdoll.store.vectordb import count, upsert_chunks

    if not paths:
        console.print("[red]Error:[/red] Provide at least one PDF file or directory.")
        raise SystemExit(1)

    pdf_paths = [Path(p) for p in paths]

    with console.status("[bold cyan]Extracting text from PDFs…"):
        docs = ingest_pdfs(pdf_paths)

    if not docs:
        console.print("[yellow]No documents extracted.[/yellow]")
        return

    console.print(f"  📄 Extracted [green]{len(docs)}[/green] document(s)")

    with console.status("[bold cyan]Chunking documents…"):
        chunks = chunk_documents(docs, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    console.print(f"  ✂️  Created [green]{len(chunks)}[/green] chunk(s)")

    with console.status("[bold cyan]Embedding and storing chunks…"):
        n = upsert_chunks(chunks)

    console.print(f"  💾 Stored [green]{n}[/green] chunk(s) in vector DB")
    console.print(f"  📊 Total chunks in collection: [bold]{count()}[/bold]")


@ingest.command("jira")
@click.option("--jql", required=True, help="JQL query to fetch issues.")
@click.option("--max-results", type=int, default=None, help="Max issues to fetch.")
@click.option("--url", default=None, help="JIRA server URL (overrides config).")
@click.option("--user", default=None, help="JIRA username (overrides config).")
@click.option("--token", default=None, help="JIRA API token / PAT (overrides config).")
@click.option("--auth-method", type=click.Choice(["pat", "basic"]), default=None, help="Auth method (overrides config).")
@click.option("--chunk-size", type=int, default=None, help="Override chunk size.")
@click.option("--chunk-overlap", type=int, default=None, help="Override chunk overlap.")
def ingest_jira(
    jql: str,
    max_results: int | None,
    url: str | None,
    user: str | None,
    token: str | None,
    auth_method: str | None,
    chunk_size: int | None,
    chunk_overlap: int | None,
) -> None:
    """Ingest JIRA issues matching a JQL query.

    For multi-site ingestion, use --url and --token to override the
    configured defaults per invocation.
    """
    from ragdoll.ingest.chunker import chunk_documents
    from ragdoll.ingest.jira import ingest_jira as _ingest_jira
    from ragdoll.store.vectordb import count, upsert_chunks

    # Temporarily override settings for this invocation.
    if url:
        settings.jira_url = url
    if user:
        settings.jira_user = user
    if token:
        settings.jira_token = token
    if auth_method:
        settings.jira_auth_method = auth_method

    with console.status("[bold cyan]Fetching JIRA issues…"):
        docs = _ingest_jira(jql, max_results=max_results)

    if not docs:
        console.print("[yellow]No issues found for the given JQL.[/yellow]")
        return

    console.print(f"  🎫 Fetched [green]{len(docs)}[/green] issue(s)")

    with console.status("[bold cyan]Chunking documents…"):
        chunks = chunk_documents(docs, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    console.print(f"  ✂️  Created [green]{len(chunks)}[/green] chunk(s)")

    with console.status("[bold cyan]Embedding and storing chunks…"):
        n = upsert_chunks(chunks)

    console.print(f"  💾 Stored [green]{n}[/green] chunk(s) in vector DB")
    console.print(f"  📊 Total chunks in collection: [bold]{count()}[/bold]")


@ingest.command("code")
@click.argument("paths", nargs=-1, type=click.Path(exists=True))
@click.option("--chunk-size", type=int, default=None, help="Override chunk size.")
@click.option("--chunk-overlap", type=int, default=None, help="Override chunk overlap.")
def ingest_code(paths: tuple[str, ...], chunk_size: int | None, chunk_overlap: int | None) -> None:
    """Ingest Python source files or directories of Python code."""
    from ragdoll.ingest.chunker import chunk_documents
    from ragdoll.ingest.code import ingest_code as _ingest_code
    from ragdoll.store.vectordb import count, upsert_chunks

    if not paths:
        console.print("[red]Error:[/red] Provide at least one Python file or directory.")
        raise SystemExit(1)

    code_paths = [Path(p) for p in paths]

    with console.status("[bold cyan]Parsing Python source files…"):
        docs = _ingest_code(code_paths)

    if not docs:
        console.print("[yellow]No Python documents extracted.[/yellow]")
        return

    console.print(f"  🐍 Extracted [green]{len(docs)}[/green] code unit(s)")

    with console.status("[bold cyan]Chunking documents…"):
        chunks = chunk_documents(docs, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    console.print(f"  ✂️  Created [green]{len(chunks)}[/green] chunk(s)")

    with console.status("[bold cyan]Embedding and storing chunks…"):
        n = upsert_chunks(chunks)

    console.print(f"  💾 Stored [green]{n}[/green] chunk(s) in vector DB")
    console.print(f"  📊 Total chunks in collection: [bold]{count()}[/bold]")


# ── Search command ─────────────────────────────────────────────────────

@cli.command()
@click.argument("query")
@click.option("-n", "--top-k", type=int, default=None, help="Number of results.")
@click.option("--source", type=click.Choice(["pdf", "jira", "code"]), default=None, help="Filter by source.")
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
@click.option("--source", type=click.Choice(["pdf", "jira", "code"]), default=None, help="Filter by source.")
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
@click.option("--source", type=click.Choice(["pdf", "jira", "code"]), default=None, help="Filter context by source.")
@click.option("-n", "--top-k", type=int, default=None, help="Number of context chunks per turn.")
def chat(source: str | None, top_k: int | None) -> None:
    """Interactive RAG chat session.

    Type your questions and get answers grounded in your ingested data.
    Type 'quit', 'exit', or Ctrl+C to end the session.
    """
    from ragdoll.query.rag import chat_with_context

    console.print(
        Panel(
            "[bold cyan]🧶 Ragdoll Chat[/bold cyan]\n\n"
            "Ask questions about your ingested JIRA tickets and documents.\n"
            "Type [bold]quit[/bold] or [bold]exit[/bold] to end the session.",
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
        except FileNotFoundError:
            pass  # first run — no history yet

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
            )

            full_response = ""
            for token in response:
                full_response += token
                console.print(token, end="")

            console.print()  # newline
            messages.append({"role": "assistant", "content": full_response})

        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")
            # Remove the failed user message to keep history clean.
            messages.pop()


# ── Status command ─────────────────────────────────────────────────────

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
