#!/usr/bin/env python3
"""
MCP Server for RenderGit - Flattens GitHub repositories into text for LLM context
"""

import argparse
import asyncio
import json
import logging
import os
import pathlib
import sys
import tempfile
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptReference,
    TextContent,
    TextResourceContents,
    Tool,
    CallToolResult,
)
from .rendergit import (
    collect_files,
    decide_file,
    generate_cxml_text,
    git_clone,
    git_head_commit,
    MAX_DEFAULT_BYTES,
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the MCP server
server = Server("rendergit-mcp")

@server.list_prompts()
async def list_prompts() -> List[PromptReference]:
    """List available prompts."""
    return [
        PromptReference(
            name="rendergit-flatten-repo",
            description="Flatten a GitHub repository into text format for LLM context",
            arguments=[
                PromptArgument(
                    name="repo_url",
                    description="GitHub repository URL to flatten",
                    required=True,
                )
            ],
        )
    ]

@server.get_prompt()
async def get_prompt(name: str, arguments: Dict[str, str] | None) -> GetPromptResult:
    """Get a specific prompt by name."""
    if name == "rendergit-flatten-repo":
        if not arguments or "repo_url" not in arguments:
            raise ValueError("Missing required argument: repo_url")
        
        repo_url = arguments["repo_url"]
        logger.info(f"Processing repository: {repo_url}")
        
        # Create a temporary directory for the cloned repo
        tmpdir = tempfile.mkdtemp(prefix="flatten_repo_")
        repo_dir = pathlib.Path(tmpdir, "repo")
        
        try:
            # Clone the repository
            logger.info(f"Cloning {repo_url} to {repo_dir}")
            git_clone(repo_url, str(repo_dir))
            
            # Get the HEAD commit
            head = git_head_commit(str(repo_dir))
            logger.info(f"Clone complete (HEAD: {head[:8]})")
            
            # Collect files
            logger.info(f"Scanning files in {repo_dir}")
            infos = collect_files(repo_dir, MAX_DEFAULT_BYTES)
            rendered_count = sum(1 for i in infos if i.decision.include)
            skipped_count = len(infos) - rendered_count
            logger.info(f"Found {len(infos)} files total ({rendered_count} will be rendered, {skipped_count} skipped)")
            
            # Generate CXML text for LLM consumption
            logger.info("Generating CXML text...")
            cxml_text = generate_cxml_text(infos, repo_dir)
            
            return GetPromptResult(
                description=f"Flattened repository {repo_url}",
                messages=[
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": f"Repository {repo_url} (commit: {head[:8]}) flattened into CXML format:\n\n{cxml_text}"
                        }
                    }
                ]
            )
        except Exception as e:
            logger.error(f"Error processing repository: {e}")
            raise
        finally:
            # Clean up temporary directory
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
    
    raise ValueError(f"Unknown prompt: {name}")

@server.list_tools()
async def list_tools() -> List[Tool]:
    """List available tools."""
    return [
        Tool(
            name="flatten_repo",
            description="Flatten a GitHub repository into text format for LLM context",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_url": {
                        "type": "string",
                        "description": "GitHub repository URL to flatten"
                    }
                },
                "required": ["repo_url"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[CallToolResult]:
    """Call a specific tool by name."""
    if name == "flatten_repo":
        if "repo_url" not in arguments:
            raise ValueError("Missing required argument: repo_url")
        
        repo_url = arguments["repo_url"]
        logger.info(f"Processing repository with tool: {repo_url}")
        
        # Create a temporary directory for the cloned repo
        tmpdir = tempfile.mkdtemp(prefix="flatten_repo_")
        repo_dir = pathlib.Path(tmpdir, "repo")
        
        try:
            # Clone the repository
            logger.info(f"Cloning {repo_url} to {repo_dir}")
            git_clone(repo_url, str(repo_dir))
            
            # Get the HEAD commit
            head = git_head_commit(str(repo_dir))
            logger.info(f"Clone complete (HEAD: {head[:8]})")
            
            # Collect files
            logger.info(f"Scanning files in {repo_dir}")
            infos = collect_files(repo_dir, MAX_DEFAULT_BYTES)
            rendered_count = sum(1 for i in infos if i.decision.include)
            skipped_count = len(infos) - rendered_count
            logger.info(f"Found {len(infos)} files total ({rendered_count} will be rendered, {skipped_count} skipped)")
            
            # Generate CXML text for LLM consumption
            logger.info("Generating CXML text...")
            cxml_text = generate_cxml_text(infos, repo_dir)
            
            # Return the result
            return [
                CallToolResult(
                    content=[
                        TextContent(
                            type="text",
                            text=f"Repository {repo_url} (commit: {head[:8]}) flattened into CXML format:\n\n{cxml_text}"
                        )
                    ],
                    isError=False
                )
            ]
        except Exception as e:
            logger.error(f"Error processing repository: {e}")
            return [
                CallToolResult(
                    content=[
                        TextContent(
                            type="text",
                            text=f"Error processing repository {repo_url}: {str(e)}"
                        )
                    ],
                    isError=True
                )
            ]
        finally:
            # Clean up temporary directory
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
    
    raise ValueError(f"Unknown tool: {name}")

async def main():
    """Main entry point for the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, {
            "version": "0.1.0",
            "capabilities": {
                "prompts": {},
                "tools": {},
                "resources": {}
            }
        })

if __name__ == "__main__":
    asyncio.run(main())