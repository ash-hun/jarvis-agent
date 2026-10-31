"""mcp 의 mcp_loader: MCP 툴을 열거해 등록하고(서버별 실패 격리), 호출 결과와 오류, 시간 초과, http 헤더를 검증한다."""

import sys
import pytest
import asyncio
import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from jarvis.core.tools.mcp_loader import MCPToolLoader, MCPToolWrapper, call_mcp_tool
from jarvis.core.tools.tools_registry import ToolRegistry
from jarvis.jarvis_config import MCPServerConfig

LIST_TOOLS = "jarvis.core.tools.mcp_loader._list_mcp_tools"
CALL_TOOL = "jarvis.core.tools.mcp_loader.call_mcp_tool"


def _wrapper(timeout: float = 30.0) -> MCPToolWrapper:
    server = MCPServerConfig(name="test-server", transport="stdio", command=["echo", "hi"], timeout=timeout)
    return MCPToolWrapper(
        server_config=server,
        tool_name="my-tool",
        description="A test MCP tool",
        input_schema={"type": "object", "properties": {"arg": {"type": "string"}}},
    )


async def test_wrapper_returns_mcp_result_as_tool_result():
    wrapper = _wrapper()

    with patch(CALL_TOOL, new_callable=AsyncMock, return_value="Tool executed successfully"):
        result = await wrapper.execute("call_01", {"arg": "value"})

    assert (wrapper.name, wrapper.description, wrapper.execution_mode) == ("my-tool", "A test MCP tool", "parallel")
    assert result.is_error is False
    assert "Tool executed successfully" in result.content[0].text


async def _hang(*a, **k):  # type: ignore[no-untyped-def]
    await asyncio.sleep(10)


@pytest.mark.parametrize(
    ("side_effect", "timeout", "text"),
    [(RuntimeError("Connection refused"), 30.0, "Connection refused"), (_hang, 0.05, "timed out")],
)
async def test_wrapper_reports_failure_or_timeout_as_error(side_effect, timeout, text):
    with patch(CALL_TOOL, side_effect=side_effect):
        result = await _wrapper(timeout).execute("c1", {"arg": "value"})

    assert result.is_error is True
    assert text in result.content[0].text


async def test_load_servers_skips_when_mcp_not_installed():
    registry = ToolRegistry()

    with patch.dict(sys.modules, {"mcp": None}):
        loaded = await MCPToolLoader(registry).load_servers([MCPServerConfig(name="test", command=["npx", "server"])])

    assert loaded == []
    assert registry.list_all() == []


async def test_load_servers_registers_named_tools():
    registry = ToolRegistry()
    tools = [
        {"name": "list-files", "description": "List files", "inputSchema": {}},
        {"name": "read-file", "description": "Read", "inputSchema": {"type": "object", "properties": {"path": {}}}},
        {"description": "no name", "inputSchema": {}},
    ]

    with patch(LIST_TOOLS, new_callable=AsyncMock, return_value=tools), patch.dict(sys.modules, {"mcp": MagicMock()}):
        loaded = await MCPToolLoader(registry).load_servers([MCPServerConfig(name="s", command=["x"])])

    assert loaded == ["list-files", "read-file"]
    assert registry.get("list-files") is not None and registry.get("read-file") is not None


@pytest.mark.parametrize("failure", ["error", "timeout"])
async def test_load_servers_skips_a_failing_server_and_continues(failure):
    registry = ToolRegistry()
    servers = [
        MCPServerConfig(name="bad", command=["bad"], timeout=0.05),
        MCPServerConfig(name="ok", command=["ok"], timeout=5.0),
    ]

    async def fake_list(server: MCPServerConfig):  # type: ignore[no-untyped-def]
        if server.name == "bad":
            if failure == "error":
                raise ConnectionError("Server unavailable")
            await asyncio.sleep(10)
        return [{"name": "ok-tool", "description": "", "inputSchema": {}}]

    with patch(LIST_TOOLS, side_effect=fake_list), patch.dict(sys.modules, {"mcp": MagicMock()}):
        loaded = await MCPToolLoader(registry).load_servers(servers)

    assert loaded == ["ok-tool"]
    assert registry.get("ok-tool") is not None


class _FakeHttpMcp:
    """sse_client 와 ClientSession 대역. 받은 헤더를 기록하고 정한 content 블록을 돌려준다."""

    def __init__(self, blocks: list) -> None:  # type: ignore[type-arg]
        self.blocks = blocks
        self.headers: list = []  # type: ignore[type-arg]

    @contextlib.asynccontextmanager
    async def sse_client(self, url, headers=None):  # type: ignore[no-untyped-def]
        self.headers.append(headers)
        yield None, None

    def session(self, read, write):  # type: ignore[no-untyped-def]
        fake = self

        class _Session:
            async def __aenter__(self):  # type: ignore[no-untyped-def]
                return self

            async def __aexit__(self, *exc):  # type: ignore[no-untyped-def]
                return None

            async def initialize(self) -> None:
                return None

            async def call_tool(self, name, params):  # type: ignore[no-untyped-def]
                return SimpleNamespace(content=fake.blocks)

        return _Session()


@pytest.fixture
def http_mcp(monkeypatch):
    def install(blocks: list) -> _FakeHttpMcp:  # type: ignore[type-arg]
        fake = _FakeHttpMcp(blocks)
        monkeypatch.setattr("mcp.client.sse.sse_client", fake.sse_client)
        monkeypatch.setattr("mcp.ClientSession", fake.session)
        return fake

    return install


@pytest.mark.parametrize(
    ("blocks", "text"),
    [([SimpleNamespace(text="Hello"), SimpleNamespace(text="World")], "Hello\nWorld"), ([], "(empty)")],
)
async def test_call_mcp_tool_joins_text_blocks(http_mcp, blocks, text):
    http_mcp(blocks)
    server = MCPServerConfig(name="s", transport="http", url="http://x/sse")

    assert await call_mcp_tool(server, "t", {}) == text


@pytest.mark.parametrize(
    ("kw", "headers"),
    [
        ({}, None),
        ({"auth_token": "secret123"}, {"Authorization": "Bearer secret123"}),
        ({"auth_token": "tok", "headers": {"X-Custom": "v"}}, {"Authorization": "Bearer tok", "X-Custom": "v"}),
        ({"auth_token": "tok", "headers": {"Authorization": "Custom xyz"}}, {"Authorization": "Custom xyz"}),
    ],
)
async def test_call_mcp_tool_sends_auth_and_custom_http_headers(http_mcp, kw, headers):
    fake = http_mcp([SimpleNamespace(text="ok")])
    server = MCPServerConfig(name="s", transport="http", url="http://x/sse", **kw)

    await call_mcp_tool(server, "t", {})

    assert fake.headers == [headers]
