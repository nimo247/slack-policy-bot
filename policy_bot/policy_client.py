import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool

TOOL_NAME = "search_academic_policy"


@asynccontextmanager
async def open_policy_session() -> AsyncIterator[tuple[ClientSession, Tool]]:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "policy_bot.policy_mcp"],
    )
    async with stdio_client(server) as (reader, writer):
        async with ClientSession(
            reader, writer, read_timeout_seconds=timedelta(seconds=90)
        ) as session:
            await session.initialize()
            available_tools = await session.list_tools()
            for tool in available_tools.tools:
                if tool.name == TOOL_NAME:
                    yield session, tool
                    return
            raise RuntimeError(f"MCP server did not expose {TOOL_NAME}")
