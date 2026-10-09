from __future__ import annotations

import asyncio
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
            result_text = await asyncio.wait_for(
                call_mcp_tool(self._server, self.name, params),
                timeout=self._server.timeout,
            )
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=result_text)],
            )
        except TimeoutError:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(
                    text=f"MCP tool '{self.name}' timed out after {self._server.timeout}s "
                         f"(server '{self._server.name}')"
                )],
                is_error=True,
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
            # 서버별 격리 — 한 서버의 실패/타임아웃이 다른 서버 로딩을 막지 않는다.
            try:
                tools = await asyncio.wait_for(
                    _list_mcp_tools(server), timeout=server.timeout
                )
            except TimeoutError:
                print(
                    f"[MCPToolLoader] '{server.name}' timed out after {server.timeout}s "
                    f"— skipping"
                )
                continue
            except Exception as exc:
                print(f"[MCPToolLoader] Failed to load from '{server.name}': {exc}")
                continue

            count = 0
            for tool in tools:
                name = tool.get("name")
                if not name:
                    print(f"[MCPToolLoader] '{server.name}': skipping tool with no name")
                    continue
                wrapper = MCPToolWrapper(
                    server_config=server,
                    tool_name=name,
                    description=tool.get("description", ""),
                    input_schema=tool.get("inputSchema", {}),
                )
                self._registry.register_force(wrapper)
                loaded.append(name)
                count += 1
            print(f"[MCPToolLoader] Loaded {count} tool(s) from '{server.name}'")

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
        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return _tools_to_dicts(result.tools)

    if server.transport == "http":
        if not server.url:
            raise ValueError(f"MCP server '{server.name}': transport=http requires url")
        from mcp.client.sse import sse_client
        async with sse_client(server.url, headers=_build_http_headers(server)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return _tools_to_dicts(result.tools)

    raise ValueError(f"Unsupported MCP transport '{server.transport}' for '{server.name}'")


async def call_mcp_tool(server: MCPServerConfig, tool_name: str, params: dict[str, Any]) -> str:
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
        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, params)
            return _extract_result_text(result)

    if server.transport == "http":
        if not server.url:
            raise ValueError(f"MCP server '{server.name}': transport=http requires url")
        from mcp.client.sse import sse_client
        async with sse_client(server.url, headers=_build_http_headers(server)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, params)
                return _extract_result_text(result)

    raise ValueError(f"Unsupported MCP transport '{server.transport}'")


def _build_http_headers(server: MCPServerConfig) -> dict[str, str] | None:
    """http transport용 헤더 구성. auth_token이 있으면 Authorization: Bearer로 추가.

    명시적으로 지정한 headers가 auth_token 파생 헤더보다 우선한다.
    헤더가 없으면 None을 반환해 mcp 기본 동작을 따른다.
    """
    headers: dict[str, str] = {}
    if server.auth_token is not None:
        headers["Authorization"] = f"Bearer {server.auth_token.get_secret_value()}"
    headers.update(server.headers)
    return headers or None


def _tools_to_dicts(tools: Any) -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "inputSchema": getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {},
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
