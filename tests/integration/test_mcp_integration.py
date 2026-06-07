"""MCP stdio transport 통합 테스트 — 실제 in-process MCP 서버 대상.

`mcp` 패키지가 설치돼 있어야 실행된다 (없으면 모듈 전체 skip).
설치: uv sync --extra mcp
"""
from __future__ import annotations

import sys

import pytest

pytest.importorskip("mcp")

# FastMCP 기반 최소 stdio 서버 — 서브프로세스로 기동된다.
_SERVER_SRC = '''
from mcp.server.fastmcp import FastMCP

server = FastMCP("jarvis-itest")


@server.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@server.tool()
def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"


if __name__ == "__main__":
    server.run()
'''


@pytest.fixture
def stdio_server(tmp_path):
    from jarvis.config import MCPServerConfig

    script = tmp_path / "mcp_server.py"
    script.write_text(_SERVER_SRC)
    return MCPServerConfig(
        name="itest",
        transport="stdio",
        command=[sys.executable, str(script)],
        timeout=30.0,
    )


async def test_stdio_tool_discovery(stdio_server):
    """실제 stdio MCP 서버에서 툴 목록을 열거해 레지스트리에 등록한다."""
    from jarvis.core.tools.mcp_loader import MCPToolLoader
    from jarvis.core.tools.registry import ToolRegistry

    registry = ToolRegistry()
    loaded = await MCPToolLoader(registry).load_servers([stdio_server])

    assert "add" in loaded
    assert "greet" in loaded
    add_tool = registry.get("add")
    assert add_tool is not None
    assert "a" in add_tool.parameters.get("properties", {})


async def test_stdio_tool_execution(stdio_server):
    """등록된 MCP 툴을 실제 서버에 호출해 결과를 받는다."""
    from jarvis.core.tools.mcp_loader import MCPToolLoader
    from jarvis.core.tools.registry import ToolRegistry

    registry = ToolRegistry()
    await MCPToolLoader(registry).load_servers([stdio_server])

    add_tool = registry.get("add")
    result = await add_tool.execute("c1", {"a": 2, "b": 3})
    assert result.is_error is False
    assert "5" in result.content[0].text

    greet_tool = registry.get("greet")
    result = await greet_tool.execute("c2", {"name": "Jarvis"})
    assert result.is_error is False
    assert "Hello, Jarvis!" in result.content[0].text


async def test_stdio_missing_command_raises():
    """stdio transport인데 command가 없으면 명확한 에러."""
    from jarvis.config import MCPServerConfig
    from jarvis.core.tools.mcp_loader import _list_mcp_tools

    server = MCPServerConfig(name="bad", transport="stdio", command=[])
    with pytest.raises(ValueError, match="requires command"):
        await _list_mcp_tools(server)
