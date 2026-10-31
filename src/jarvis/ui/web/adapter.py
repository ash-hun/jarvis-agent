"""[ui] PerConnectionAdapter: 에이전트 이벤트를 WebSocket 연결 하나로 보낸다."""

import contextlib
from typing import TYPE_CHECKING

from jarvis.agent_layer.agent_types import AgentEvent
from jarvis.ui.web.approvals import Connection
from jarvis.ui.ui_protocol import UIAdapter

if TYPE_CHECKING:
    from fastapi import WebSocket


class PerConnectionAdapter(UIAdapter, Connection):
    """WebSocket 연결 하나의 어댑터. 이벤트를 그 연결에만 보낸다. 승인은 세션 단위(SessionApprovals)라 받지 않는다."""

    def __init__(self, ws: "WebSocket") -> None:
        self._ws = ws

    async def on_agent_event(self, event: AgentEvent) -> None:
        payload = event.model_dump()
        payload["type"] = getattr(event, "type", "unknown")
        with contextlib.suppress(Exception):
            await self._ws.send_json(payload)

    async def send(self, payload: dict[str, object]) -> None:
        """임의 메시지를 이 연결로 보낸다(스케줄 알림 방송 등). 끊긴 연결이면 조용히 넘어간다."""
        with contextlib.suppress(Exception):
            await self._ws.send_json(payload)

    async def on_stream_text(self, delta: str) -> None:
        with contextlib.suppress(Exception):
            await self._ws.send_json({"type": "stream_delta", "text": delta})

    async def show_error(self, error: str) -> None:
        with contextlib.suppress(Exception):
            await self._ws.send_json({"type": "error", "message": error})
