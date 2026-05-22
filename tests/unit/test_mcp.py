"""MCPToolLoader / MCPToolWrapper 테스트."""
from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMCPToolWrapper:
    def _make_wrapper(self):
        from jarvis.config import MCPServerConfig
        from jarvis.core.tools.mcp_loader import MCPToolWrapper

        server = MCPServerConfig(name="test-server", transport="stdio", command=["echo", "hi"])
        return MCPToolWrapper(
            server_config=server,
            tool_name="my-tool",
            description="A test MCP tool",
            input_schema={"type": "object", "properties": {"arg": {"type": "string"}}},
        )

    def test_wrapper_metadata(self):
        wrapper = self._make_wrapper()
        assert wrapper.name == "my-tool"
        assert wrapper.description == "A test MCP tool"
        assert wrapper.execution_mode == "parallel"

    async def test_execute_success(self):
        wrapper = self._make_wrapper()

        with patch("jarvis.core.tools.mcp_loader._call_mcp_tool", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "Tool executed successfully"
            result = await wrapper.execute("call_01", {"arg": "value"})

        assert result.is_error is False
        assert "Tool executed successfully" in result.content[0].text

    async def test_execute_error_on_exception(self):
        wrapper = self._make_wrapper()

        with patch("jarvis.core.tools.mcp_loader._call_mcp_tool", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = RuntimeError("Connection refused")
            result = await wrapper.execute("call_01", {"arg": "value"})

        assert result.is_error is True
        assert "Connection refused" in result.content[0].text


class TestMCPToolLoader:
    def _make_loader(self):
        from jarvis.core.tools.registry import ToolRegistry
        from jarvis.core.tools.mcp_loader import MCPToolLoader

        registry = ToolRegistry()
        return MCPToolLoader(registry), registry

    async def test_load_servers_skips_when_mcp_not_installed(self):
        loader, registry = self._make_loader()
        from jarvis.config import MCPServerConfig

        servers = [MCPServerConfig(name="test", transport="stdio", command=["npx", "server"])]

        # mcp 패키지가 없는 환경 시뮬레이션
        with patch.dict(sys.modules, {"mcp": None}):
            loaded = await loader.load_servers(servers)

        assert loaded == []
        assert len(registry.list_all()) == 0

    async def test_load_servers_registers_tools(self):
        loader, registry = self._make_loader()
        from jarvis.config import MCPServerConfig

        servers = [MCPServerConfig(name="test", transport="stdio", command=["npx", "server"])]

        mock_tools = [
            {"name": "list-files", "description": "List files", "inputSchema": {}},
            {"name": "read-file", "description": "Read a file", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}}},
        ]

        with patch("jarvis.core.tools.mcp_loader._list_mcp_tools", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = mock_tools
            # mcp import을 mock으로 허용
            mock_mcp = MagicMock()
            with patch.dict(sys.modules, {"mcp": mock_mcp}):
                loaded = await loader.load_servers(servers)

        assert "list-files" in loaded
        assert "read-file" in loaded
        assert registry.get("list-files") is not None
        assert registry.get("read-file") is not None

    async def test_load_servers_continues_on_server_error(self):
        loader, registry = self._make_loader()
        from jarvis.config import MCPServerConfig

        servers = [
            MCPServerConfig(name="bad-server", transport="stdio", command=["bad-cmd"]),
            MCPServerConfig(name="good-server", transport="stdio", command=["good-cmd"]),
        ]

        good_tools = [{"name": "good-tool", "description": "", "inputSchema": {}}]

        async def fake_list(server: MCPServerConfig):
            if server.name == "bad-server":
                raise ConnectionError("Server unavailable")
            return good_tools

        mock_mcp = MagicMock()
        with patch("jarvis.core.tools.mcp_loader._list_mcp_tools", side_effect=fake_list):
            with patch.dict(sys.modules, {"mcp": mock_mcp}):
                loaded = await loader.load_servers(servers)

        assert "good-tool" in loaded
        assert registry.get("good-tool") is not None


class TestMCPConfig:
    def test_server_config_defaults(self):
        from jarvis.config import MCPServerConfig

        cfg = MCPServerConfig(name="my-server")
        assert cfg.transport == "stdio"
        assert cfg.command == []
        assert cfg.url is None
        assert cfg.env == {}

    def test_server_config_http(self):
        from jarvis.config import MCPServerConfig

        cfg = MCPServerConfig(name="http-server", transport="http", url="http://localhost:8080/sse")
        assert cfg.transport == "http"
        assert cfg.url == "http://localhost:8080/sse"

    def test_extract_result_text(self):
        from jarvis.core.tools.mcp_loader import _extract_result_text

        mock_result = MagicMock()
        block1 = MagicMock()
        block1.text = "Hello"
        block2 = MagicMock()
        block2.text = "World"
        mock_result.content = [block1, block2]

        text = _extract_result_text(mock_result)
        assert text == "Hello\nWorld"

    def test_extract_result_text_empty(self):
        from jarvis.core.tools.mcp_loader import _extract_result_text

        mock_result = MagicMock()
        mock_result.content = []
        assert _extract_result_text(mock_result) == "(empty)"
