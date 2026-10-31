"""external 기능의 MCP 소스: 툴 호출 인자 전달, 실패 격리, 소스 목록 조립을 검증한다."""

import json
import pytest
import asyncio

from jarvis.core.external import ExternalSource, ExternalSourceSpec, McpToolSource, build_mcp_sources
from jarvis.jarvis_config import MCPServerConfig


def _server(**kw) -> MCPServerConfig:
    return MCPServerConfig(name="gcal", transport="stdio", command=["x"], **kw)


def _spec(**kw) -> ExternalSourceSpec:
    base = {"name": "cal", "server": "gcal", "tool": "list_events"}
    return ExternalSourceSpec(**{**base, **kw})


async def _hang(server, tool, params) -> str:
    await asyncio.sleep(10)
    return ""


async def _boom(server, tool, params) -> str:
    raise RuntimeError("server down")


@pytest.mark.asyncio
async def test_poll_passes_args_to_tool_call() -> None:
    seen_args: dict = {}

    async def fake_call(server, tool, params):
        seen_args.update({"server": server.name, "tool": tool, "params": params})
        return json.dumps([{"id": "e1", "summary": "회의"}])

    source = McpToolSource(_spec(args={"time_min": "now"}), _server(), call=fake_call)

    events = await source.poll()

    assert seen_args == {"server": "gcal", "tool": "list_events", "params": {"time_min": "now"}}
    assert [e.key for e in events] == ["cal:e1"]
    assert isinstance(source, ExternalSource)


@pytest.mark.parametrize(("call", "server_kw"), [(_hang, {"timeout": 0.01}), (_boom, {})], ids=["timeout", "error"])
@pytest.mark.asyncio
async def test_poll_returns_empty_on_failure(call, server_kw: dict) -> None:
    source = McpToolSource(_spec(), _server(**server_kw), call=call)

    assert await source.poll() == []


def test_build_mcp_sources_skips_disabled_and_unknown_server() -> None:
    specs = [_spec(name="ok"), _spec(name="off", enabled=False), _spec(name="ghost", server="nope")]

    sources = build_mcp_sources(specs, [_server()])

    assert [s.name for s in sources] == ["ok"]
