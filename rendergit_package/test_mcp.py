#!/usr/bin/env python3
"""
Test script for the RenderGit MCP server
"""

import asyncio
import json
import sys
from mcp.client.stdio import stdio_client
from mcp.types import ClientCapabilities, ClientNotificationOptions

async def test_mcp_server():
    """Test the MCP server functionality"""
    async with stdio_client(["python", "-m", "mcp_server"]) as (read, write, _):
        # Initialize the connection
        init_message = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "1.0.0",
                "clientInfo": {
                    "name": "test-client",
                    "version": "1.0.0"
                },
                "capabilities": {}
            }
        }
        
        write(init_message)
        response = await read()
        print(f"Initialize response: {json.dumps(response, indent=2)}")
        
        # List tools
        list_tools_message = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list"
        }
        
        write(list_tools_message)
        response = await read()
        print(f"List tools response: {json.dumps(response, indent=2)}")
        
        # Call the flatten_repo tool
        call_tool_message = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "flatten_repo",
                "arguments": {
                    "repo_url": "https://github.com/karpathy/randomfun"
                }
            }
        }
        
        write(call_tool_message)
        response = await read()
        print(f"Call tool response: {json.dumps(response, indent=2)}")
        
        # Shutdown
        shutdown_message = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "shutdown"
        }
        
        write(shutdown_message)
        response = await read()
        print(f"Shutdown response: {json.dumps(response, indent=2)}")

if __name__ == "__main__":
    asyncio.run(test_mcp_server())