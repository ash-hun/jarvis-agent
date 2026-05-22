from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jarvis.config import MCPServerConfig
    from jarvis.core.tools.registry import ToolRegistry


class MCPToolWrapper:
    """MCP 서버 단일 툴을 JarvisTool Protocol로 래핑."""

    def __init__(
        self,
        server_config: MCPServerConfig,
        tool_name: str,
        description: str,
        input_schema: dict[str, Any],
    ) -> None:
        self.name = tool_name
        self.description = description
        self.parameters = input_schema or {"type": "object", "properties": {}}
        self.execution_mode = "parallel"
        self._server = server_config

    async def execute(self, tool_call_id: str, params: dict[str, Any], signal: Any = None) -> Any:
        from jarvis.model_layer.types import TextContent, ToolResultMessage

        try:
            result_text = await _call_mcp_tool(self._server, self.name, params)
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=result_text)],
            )
        except Exception as exc:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=str(exc))],
                is_error=True,
            )


class MCPToolLoader:
    """MCP 서버에 연결해 툴을 열거하고 ToolRegistry에 등록한다."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def load_servers(self, servers: list[MCPServerConfig]) -> list[str]:
        """각 서버에 연결해 툴 목록을 등록. mcp 패키지 없으면 skip. Returns registered tool names."""
        try:
            import mcp  # noqa: F401
        except ImportError:
            print("[MCPToolLoader] mcp package not installed — skipping. Run: uv add mcp")
            return []

        loaded: list[str] = []
        for server in servers:
            try:
                tools = await _list_mcp_tools(server)
                for tool in tools:
                    wrapper = MCPToolWrapper(
                        server_config=server,
                        tool_name=tool["name"],
                        description=tool.get("description", ""),
                        input_schema=tool.get("inputSchema", {}),
                    )
                    self._registry.register_force(wrapper)
                    loaded.append(tool["name"])
                print(f"[MCPToolLoader] Loaded {len(tools)} tool(s) from '{server.name}'")
            except Exception as exc:
                print(f"[MCPToolLoader] Failed to load from '{server.name}': {exc}")

        return loaded


async def _list_mcp_tools(server: MCPServerConfig) -> list[dict[str, Any]]:
    from mcp import ClientSession
    if server.transport == "stdio":
        if not server.command:
            raise ValueError(f"MCP server '{server.name}': transport=stdio requires command")
        from mcp.client.stdio import StdioServerParameters, stdio_client
        server_params = StdioServerParameters(
            command=server.command[0],
            args=server.command[1:],
            env=server.env or None,
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return _tools_to_dicts(result.tools)

    if server.transport == "http":
        if not server.url:
            raise ValueError(f"MCP server '{server.name}': transport=http requires url")
        from mcp.client.sse import sse_client
        async with sse_client(server.url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return _tools_to_dicts(result.tools)

    raise ValueError(f"Unsupported MCP transport '{server.transport}' for '{server.name}'")


async def _call_mcp_tool(server: MCPServerConfig, tool_name: str, params: dict[str, Any]) -> str:
    from mcp import ClientSession
    if server.transport == "stdio":
        if not server.command:
            raise ValueError(f"MCP server '{server.name}': transport=stdio requires command")
        from mcp.client.stdio import StdioServerParameters, stdio_client
        server_params = StdioServerParameters(
            command=server.command[0],
            args=server.command[1:],
            env=server.env or None,
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, params)
                return _extract_result_text(result)

    if server.transport == "http":
        if not server.url:
            raise ValueError(f"MCP server '{server.name}': transport=http requires url")
        from mcp.client.sse import sse_client
        async with sse_client(server.url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, params)
                return _extract_result_text(result)

    raise ValueError(f"Unsupported MCP transport '{server.transport}'")


def _tools_to_dicts(tools: Any) -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "inputSchema": getattr(t, "inputSchema", {}),
        }
        for t in tools
    ]


def _extract_result_text(result: Any) -> str:
    parts: list[str] = []
    for block in result.content:
        if hasattr(block, "text"):
            parts.append(block.text)
        else:
            try:
                parts.append(json.dumps(block.model_dump()))
            except Exception:
                parts.append(str(block))
    return "\n".join(parts) or "(empty)"
