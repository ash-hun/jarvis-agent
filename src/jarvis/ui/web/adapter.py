from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from jarvis.agent_layer.types import AgentEvent

if TYPE_CHECKING:
    from fastapi import WebSocket


class PerConnectionAdapter:
    """
    WebSocket 연결 1개에 대응하는 어댑터.
    이벤트를 해당 연결에만 전달한다. 승인은 세션 단위(SessionApprovals)다.
    """

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws

    async def on_agent_event(self, event: AgentEvent) -> None:
        payload = event.model_dump()
        payload["type"] = getattr(event, "type", "unknown")
        with contextlib.suppress(Exception):
            await self._ws.send_json(payload)

    async def send(self, payload: dict) -> None:
        """임의 메시지를 이 연결로 보낸다(스케줄 알림 방송 등). 끊긴 연결이면 조용히 넘어간다."""
        with contextlib.suppress(Exception):
            await self._ws.send_json(payload)

    async def on_stream_text(self, delta: str) -> None:
        with contextlib.suppress(Exception):
            await self._ws.send_json({"type": "stream_delta", "text": delta})

    async def show_error(self, error: str) -> None:
        with contextlib.suppress(Exception):
            await self._ws.send_json({"type": "error", "message": error})
