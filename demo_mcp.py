#!/usr/bin/env python3
"""
Example script demonstrating how to use the RenderGit MCP server programmatically
"""

import asyncio
import json
import subprocess
import sys
import time

async def demonstrate_mcp_usage():
    """Demonstrate how to use the RenderGit MCP server"""
    print("Demonstrating RenderGit MCP server usage...")
    
    # Start the MCP server as a subprocess
    server_process = subprocess.Popen(
        [sys.executable, "-m", "rendergit_package.mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=0
    )
    
    # Give the server a moment to start
    time.sleep(2)
    
    # Check if the process is still running
    if server_process.poll() is not None:
        stderr = server_process.stderr.read()
        print(f"Server failed to start: {stderr}")
        return
    
    print("✓ MCP server started successfully")
    print("\nYou can now use this server with any MCP-compatible client, such as:")
    print("- Claude Desktop")
    print("- Other MCP tools that support the Model Context Protocol")
    print("\nTo use with Claude Desktop, add this to your configuration:")
    print("""

{
  "mcpServers": {
    "rendergit": {
      "command": "rendergit-mcp"
    }
  }
}

""")
    
    # Terminate the server
    server_process.terminate()
    try:
        server_process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server_process.kill()
    
    print("✓ MCP server demonstration completed")

if __name__ == "__main__":
    asyncio.run(demonstrate_mcp_usage())
