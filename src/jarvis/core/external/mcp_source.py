from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from jarvis.core.external.dedup import derive_events
from jarvis.core.external.loader import ExternalSourceSpec
from jarvis.core.external.types import ExternalEvent

if TYPE_CHECKING:
    from jarvis.config import MCPServerConfig

# (server, tool_name, params) -> 원문 텍스트. 기본은 mcp_loader.call_mcp_tool.
CallMcpTool = Callable[["MCPServerConfig", str, dict[str, Any]], Awaitable[str]]


class McpToolSource:
    """MCP 툴을 1회 호출해 원문을 이벤트로 변환하는 소스.

    ToolRegistry를 경유하지 않고 서버를 직접 지정 호출한다 — 서로 다른 서버가
    같은 툴 이름을 쓰면 register_force로 덮여 충돌하기 때문(설계 §5).
    poll()은 예외를 던지지 않는다: 서버 무응답·오류는 빈 목록 + 로그로 끝난다.
    """

    def __init__(
        self,
        spec: ExternalSourceSpec,
        server: MCPServerConfig,
        *,
        call: CallMcpTool | None = None,
        detail_max_chars: int = 500,
    ) -> None:
        self.name = spec.name
        self.interval_sec = spec.interval_sec
        self._spec = spec
        self._server = server
        self._call = call
        self._detail_max_chars = detail_max_chars

    async def poll(self) -> list[ExternalEvent]:
        call = self._call
        if call is None:
            from jarvis.core.tools.mcp_loader import call_mcp_tool

            call = call_mcp_tool

        try:
            raw = await asyncio.wait_for(
                call(self._server, self._spec.tool, dict(self._spec.args)),
                timeout=self._server.timeout,
            )
        except TimeoutError:
            print(
                f"[McpToolSource] '{self.name}': '{self._spec.tool}' timed out after "
                f"{self._server.timeout}s (server '{self._server.name}') — skipping"
            )
            return []
        except Exception as exc:
            print(f"[McpToolSource] '{self.name}': poll failed: {exc}")
            return []

        return derive_events(self.name, raw, detail_max_chars=self._detail_max_chars)


def build_mcp_sources(
    specs: list[ExternalSourceSpec],
    servers: list[MCPServerConfig],
    *,
    detail_max_chars: int = 500,
    call: CallMcpTool | None = None,
) -> list[McpToolSource]:
    """소스 선언 + MCP 서버 설정 → McpToolSource 목록.

    비활성 소스는 건너뛰고, 미지의 서버 이름은 경고 후 그 소스만 skip한다
    (MCPToolLoader의 서버별 격리 규약과 동일).
    """
    by_name = {s.name: s for s in servers}
    sources: list[McpToolSource] = []
    for spec in specs:
        if not spec.enabled:
            continue
        server = by_name.get(spec.server)
        if server is None:
            print(
                f"[ExternalSourceLoader] '{spec.name}': unknown MCP server "
                f"'{spec.server}' — skipping"
            )
            continue
        sources.append(
            McpToolSource(spec, server, call=call, detail_max_chars=detail_max_chars)
        )
    return sources
