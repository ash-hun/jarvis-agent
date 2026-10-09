from __future__ import annotations

import asyncio
import contextlib
import uuid
from typing import TYPE_CHECKING

from jarvis.agent_layer.types import AgentEvent

if TYPE_CHECKING:
    from fastapi import WebSocket


class PerConnectionAdapter:
    """
    WebSocket 연결 1개에 대응하는 어댑터.
    이벤트 브로드캐스트와 approval을 해당 연결에만 전달한다.
    """

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws
        self._pending_approvals: dict[str, asyncio.Future[bool | str]] = {}

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

    async def request_approval(self, command: str, reason: str, always_pattern: str = "") -> bool | str:
        approval_id = str(uuid.uuid4())
        future: asyncio.Future[bool | str] = asyncio.get_event_loop().create_future()
        self._pending_approvals[approval_id] = future
        try:
            await self._ws.send_json({
                "type": "approval_request",
                "id": approval_id,
                "command": command[:500],
                "reason": reason,
                "always_pattern": always_pattern,
            })
        except Exception:
            self._pending_approvals.pop(approval_id, None)
            return False
        try:
            return await asyncio.wait_for(future, timeout=120.0)
        except TimeoutError:
            return False
        finally:
            self._pending_approvals.pop(approval_id, None)

    async def handle_approval_response(self, approval_id: str, approved: bool, always: bool = False) -> None:
        """always 는 "이 패턴을 앞으로 묻지 않기". 거부하면서 always 일 수는 없다."""
        future = self._pending_approvals.get(approval_id)
        if future and not future.done():
            future.set_result("always" if approved and always else approved)
