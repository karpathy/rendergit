#!/usr/bin/env python3
"""
Test script for the RenderGit MCP server
"""

import asyncio
import subprocess
import sys
import time

async def test_mcp_server():
    """Test the MCP server functionality"""
    print("Testing RenderGit MCP server...")
    
    # Start the MCP server as a subprocess
    try:
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
            return False
        
        print("✓ MCP server started successfully")
        
        # Terminate the server
        server_process.terminate()
        try:
            server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_process.kill()
        
        print("✓ MCP server test completed")
        return True
        
    except Exception as e:
        print(f"Error testing MCP server: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_mcp_server())
    if success:
        print("All tests passed!")
        sys.exit(0)
    else:
        print("Tests failed!")
        sys.exit(1)