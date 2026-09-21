"""Thin helper for calling tools on the local MCP server over stdio.

Spawns the server per call. Simple and fine for a demo; swap for a
long-lived session later if latency ever matters.
"""

import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_PATH = Path(__file__).parent.parent / "mcp_server" / "server.py"


async def call_tool(name: str, arguments: dict | None = None) -> list[dict]:
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER_PATH)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments or {})
            if result.isError:
                raise RuntimeError(f"MCP tool {name} failed: {result.content}")
            # list-returning tools come back as one JSON text block per item
            return [json.loads(block.text) for block in result.content]
