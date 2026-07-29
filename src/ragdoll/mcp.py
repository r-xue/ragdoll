"""Model Context Protocol (MCP) server for Ragdoll."""

from fastmcp import FastMCP
from ragdoll.query.retriever import search

# Create the MCP server
mcp = FastMCP("Ragdoll")

@mcp.tool()
def search_ragdoll(query: str, top_k: int = 5, source_filter: str = None) -> str:
    """
    Search the Ragdoll vector database for context.
    
    Args:
        query: The natural language query to search for (e.g. "How does the calibration pipeline work?")
        top_k: Number of results to return (default: 5)
        source_filter: Optional source to restrict to (e.g. "jira", "git", "code", "pdf", "bitbucket")
        
    Returns:
        A formatted string of search results to be used as context by the LLM.
    """
    # The retriever expects an integer for top_k, ensure it is.
    results = search(query=query, top_k=int(top_k), source_filter=source_filter)
    
    if not results:
        return f"No results found in Ragdoll for query: '{query}'"
        
    formatted_results = []
    for i, res in enumerate(results, 1):
        source = res.metadata.get("source", "unknown")
        header = f"--- Result {i} (Source: {source}) ---"
        
        # Build metadata context string
        meta_parts = []
        if "key" in res.metadata:
            meta_parts.append(f"Issue: {res.metadata['key']}")
        if "commit_hash" in res.metadata:
            meta_parts.append(f"Commit: {res.metadata['commit_hash']}")
        if "title" in res.metadata:
            meta_parts.append(f"Title: {res.metadata['title']}")
        elif "subject" in res.metadata:
            meta_parts.append(f"Subject: {res.metadata['subject']}")
            
        if meta_parts:
            header += f"\n{' | '.join(meta_parts)}"
            
        formatted_results.append(f"{header}\n{res.text}\n")
        
    return "\n".join(formatted_results)

def main(transport: str = "stdio", port: int = 8000):
    """Run the MCP server."""
    if transport == "sse":
        # Run over HTTP with Server-Sent Events (SSE)
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = port
        mcp.run(transport="sse")
    else:
        # Default to stdio for local command-line usage
        mcp.run()

if __name__ == "__main__":
    main()
