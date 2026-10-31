"""mcp 기능: 실제 stdio MCP 서버의 툴을 레지스트리에 등록해 호출하고, command 없는 서버는 격리됨을 검증한다."""

import sys
import pytest

pytest.importorskip("mcp")

from jarvis.core.tools.mcp_loader import MCPToolLoader, call_mcp_tool  # noqa: E402
from jarvis.core.tools.tools_registry import ToolRegistry  # noqa: E402
from jarvis.jarvis_config import MCPServerConfig  # noqa: E402

# MCPServer(mcp 2.x, 1.x 의 FastMCP) 기반 최소 stdio 서버. 서브프로세스로 기동된다
SERVER_SRC = '''
from mcp.server.mcpserver import MCPServer

server = MCPServer("jarvis-itest")


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
    script = tmp_path / "mcp_server.py"
    script.write_text(SERVER_SRC)
    return MCPServerConfig(name="itest", transport="stdio", command=[sys.executable, str(script)], timeout=30.0)


async def test_stdio_tools_are_discovered_and_executed(stdio_server):
    registry = ToolRegistry()

    loaded = await MCPToolLoader(registry).load_servers([stdio_server])
    added = await registry.get("add").execute("c1", {"a": 2, "b": 3})
    greeted = await registry.get("greet").execute("c2", {"name": "Jarvis"})

    assert {"add", "greet"} <= set(loaded)
    assert "a" in registry.get("add").parameters.get("properties", {})
    assert added.is_error is False and "5" in added.content[0].text
    assert greeted.is_error is False and "Hello, Jarvis!" in greeted.content[0].text


async def test_stdio_server_without_command_is_skipped_with_clear_error(stdio_server):
    bad = MCPServerConfig(name="bad", transport="stdio", command=[])

    loaded = await MCPToolLoader(ToolRegistry()).load_servers([bad, stdio_server])

    assert {"add", "greet"} <= set(loaded)
    with pytest.raises(ValueError, match="requires command"):
        await call_mcp_tool(bad, "add", {"a": 1, "b": 2})
