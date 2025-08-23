# RenderGit MCP Server

This directory contains an MCP (Model Context Protocol) server implementation for RenderGit that allows you to flatten GitHub repositories into text format for LLM context.

## Installation

1. Create a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. Install the package:
   ```bash
   pip install -e .
   ```

## Running the MCP Server

To start the MCP server, run:
```bash
rendergit-mcp
```

This will start the server and listen for MCP connections.

## Using with Claude Desktop

1. First, ensure you have [Claude Desktop](https://claude.ai/download) installed
2. Configure Claude Desktop to use the RenderGit MCP server by adding the following to your Claude configuration:

```json
{
  "mcpServers": {
    "rendergit": {
      "command": "rendergit-mcp"
    }
  }
}
```

3. Restart Claude Desktop
4. In any conversation with Claude, you can now use the RenderGit tool to flatten repositories

## Using the MCP Tool

Once connected, you can ask Claude to flatten a repository:

> "Please flatten the code in https://github.com/karpathy/nanoGPT for me to analyze"

Claude will use the MCP tool to clone the repository, flatten it into CXML format, and provide it for analysis.

## Testing the MCP Server

You can test the MCP server with the provided test script:
```bash
python test_mcp_server.py
```