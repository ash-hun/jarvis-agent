"""MCPToolLoader / MCPToolWrapper 테스트."""
from __future__ import annotations

import asyncio
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

    async def test_load_servers_skips_on_timeout_and_continues(self):
        """응답 없는 서버는 타임아웃 후 skip되고 다른 서버는 계속 로드된다."""
        loader, registry = self._make_loader()
        from jarvis.config import MCPServerConfig

        servers = [
            MCPServerConfig(name="hang", transport="stdio", command=["hang"], timeout=0.05),
            MCPServerConfig(name="ok", transport="stdio", command=["ok"], timeout=5.0),
        ]

        async def fake_list(server: MCPServerConfig):
            if server.name == "hang":
                await asyncio.sleep(10)  # 타임아웃보다 오래 걸림
            return [{"name": "ok-tool", "description": "", "inputSchema": {}}]

        mock_mcp = MagicMock()
        with patch("jarvis.core.tools.mcp_loader._list_mcp_tools", side_effect=fake_list):
            with patch.dict(sys.modules, {"mcp": mock_mcp}):
                loaded = await loader.load_servers(servers)

        assert loaded == ["ok-tool"]
        assert registry.get("ok-tool") is not None

    async def test_load_servers_skips_tool_with_no_name(self):
        loader, registry = self._make_loader()
        from jarvis.config import MCPServerConfig

        servers = [MCPServerConfig(name="s", transport="stdio", command=["x"])]
        tools = [
            {"name": "good", "description": "", "inputSchema": {}},
            {"description": "no name", "inputSchema": {}},
        ]

        mock_mcp = MagicMock()
        with patch("jarvis.core.tools.mcp_loader._list_mcp_tools", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = tools
            with patch.dict(sys.modules, {"mcp": mock_mcp}):
                loaded = await loader.load_servers(servers)

        assert loaded == ["good"]


class TestMCPToolWrapperTimeout:
    def _make_wrapper(self, timeout: float):
        from jarvis.config import MCPServerConfig
        from jarvis.core.tools.mcp_loader import MCPToolWrapper

        server = MCPServerConfig(name="s", transport="stdio", command=["x"], timeout=timeout)
        return MCPToolWrapper(server, "slow-tool", "", {})

    async def test_execute_times_out(self):
        wrapper = self._make_wrapper(timeout=0.05)

        async def hang(*a, **k):
            await asyncio.sleep(10)

        with patch("jarvis.core.tools.mcp_loader._call_mcp_tool", side_effect=hang):
            result = await wrapper.execute("c1", {})

        assert result.is_error is True
        assert "timed out" in result.content[0].text


class TestBuildHttpHeaders:
    def _server(self, **kw):
        from jarvis.config import MCPServerConfig

        return MCPServerConfig(name="s", transport="http", url="http://x/sse", **kw)

    def test_empty_returns_none(self):
        from jarvis.core.tools.mcp_loader import _build_http_headers

        assert _build_http_headers(self._server()) is None

    def test_auth_token_to_bearer(self):
        from jarvis.core.tools.mcp_loader import _build_http_headers

        headers = _build_http_headers(self._server(auth_token="secret123"))
        assert headers == {"Authorization": "Bearer secret123"}

    def test_custom_headers_merged(self):
        from jarvis.core.tools.mcp_loader import _build_http_headers

        headers = _build_http_headers(
            self._server(auth_token="tok", headers={"X-Custom": "v"})
        )
        assert headers["Authorization"] == "Bearer tok"
        assert headers["X-Custom"] == "v"

    def test_explicit_header_overrides_auth_token(self):
        from jarvis.core.tools.mcp_loader import _build_http_headers

        headers = _build_http_headers(
            self._server(auth_token="tok", headers={"Authorization": "Custom xyz"})
        )
        assert headers["Authorization"] == "Custom xyz"


class TestMCPConfig:
    def test_server_config_defaults(self):
        from jarvis.config import MCPServerConfig

        cfg = MCPServerConfig(name="my-server")
        assert cfg.transport == "stdio"
        assert cfg.command == []
        assert cfg.url is None
        assert cfg.env == {}
        assert cfg.timeout == 30.0
        assert cfg.headers == {}
        assert cfg.auth_token is None

    def test_server_config_auth_token_is_secret(self):
        from pydantic import SecretStr

        from jarvis.config import MCPServerConfig

        cfg = MCPServerConfig(name="s", auth_token="my-secret")
        assert isinstance(cfg.auth_token, SecretStr)
        # repr/str로 노출되지 않음
        assert "my-secret" not in str(cfg)
        assert cfg.auth_token.get_secret_value() == "my-secret"

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
