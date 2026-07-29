# Model Context Protocol (MCP) Integration

Ragdoll natively supports the **Model Context Protocol (MCP)**, allowing you to expose your local vector database as a set of dynamic tools for external AI clients like Claude Desktop, Cursor, and VS Code (via extensions).

When running as an MCP server, Ragdoll provides a `search_ragdoll` tool that external LLMs can use to search for context from your ingested Jira tickets, Bitbucket PRs, Git commits, Code, and PDFs.

There are two ways to run the Ragdoll MCP Server depending on your needs.

---

## 1. Local Transport (stdio)

If your AI client is running on the same machine as Ragdoll, the standard way to connect is using the `stdio` transport. The client will spawn the Ragdoll process in the background.

To test if the MCP server works locally, you can run:

```bash
pixi run ragdoll mcp
```

*(Note: Running this manually will appear to hang, as it waits for JSON-RPC messages on standard input).*

### Connecting to Claude Code (CLI)

If you use Anthropic's official `claude` CLI in your terminal, you can easily attach Ragdoll by running:

```bash
claude mcp add ragdoll -- /path/to/ragdoll/.pixi/envs/default/bin/ragdoll mcp
```

### Connecting to Claude Desktop

To add Ragdoll to the official Claude Desktop app, edit your configuration file (usually located at `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS or `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "ragdoll": {
      "command": "/path/to/ragdoll/.pixi/envs/default/bin/ragdoll",
      "args": ["mcp"]
    }
  }
}
```

### Connecting to VS Code

If you are using an MCP-compatible extension in VS Code:
1. Locate the MCP Server configuration settings for your extension.
2. Add Ragdoll to the `mcpServers` object in your configuration:

```json
{
  "mcpServers": {
    "ragdoll": {
      "command": "/path/to/ragdoll/.pixi/envs/default/bin/ragdoll",
      "args": ["mcp"]
    }
  }
}
```

---

## 2. Network Transport (SSE)

If your AI client is on a different machine, or if you prefer a REST-like API, you can run the MCP server over HTTP using Server-Sent Events (SSE).

To start the server in SSE mode, run:
```bash
pixi run ragdoll mcp --transport sse --port 8080
```

This starts a web server listening on port 8080. External MCP clients can now connect to this server by pointing to the SSE endpoint: `http://<your-ip>:8080/sse`.

### Connecting via SSE to IDEs and Custom Clients

If your IDE or AI client supports SSE via a standard `mcp_config.json`, you can connect by replacing the `command`/`args` array with a `url`:

```json
{
  "mcpServers": {
    "ragdoll": {
      "url": "http://127.0.0.1:8080/sse"
    }
  }
}
```

*(Note: Ensure your network allows connections to the specified port if accessing from a different machine).*

---

## Using the MCP Tool

Once your AI client is connected to Ragdoll, you don't need to learn any specific syntax. You can simply chat with your AI and ask natural language questions:

> *"Search Ragdoll for the latest Jira tickets related to the ALMA pipeline calibration bugs."*

The AI will recognize the `search_ragdoll` tool, send the query, and use the results returned from your local ChromaDB to answer your question.
