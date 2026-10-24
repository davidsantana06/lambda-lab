from fastmcp import Client
from mcp.types import Tool
from typing import Any


_MCP_SERVER_URL = "http://lambda-lab-mcp-server:9001/mcp"


async def list_tools() -> list[dict[str, Any]]:
    async with Client(_MCP_SERVER_URL) as client:
        tools = await client.list_tools()
    return [_compose_function_tool(tool) for tool in tools]


async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async with Client(_MCP_SERVER_URL) as client:
        result = await client.call_tool(name, arguments, raise_on_error=False)

    text = "\n".join(
        content.text for content in result.content if content.type == "text"
    )
    if result.is_error:
        return {"error": text}

    if result.structured_content is not None:
        return result.structured_content

    return {"result": text}


def _compose_function_tool(tool: Tool) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema,
        },
    }
