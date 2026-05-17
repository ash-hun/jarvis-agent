from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

from jarvis.agent_layer.types import AgentEvent

if TYPE_CHECKING:
    from fastapi import WebSocket


class WebUIAdapter:
    """
    UIAdapter Protocol 구현 — WebSocket 브로드캐스트 기반.
    approval은 asyncio.Future로 클라이언트 응답을 대기.
    """

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._pending_approvals: dict[str, asyncio.Future[bool]] = {}

    # ── 클라이언트 연결 관리 ───────────────────────────────────────────────────

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        # 대기 중인 승인 요청이 있으면 자동 거부
        for future in self._pending_approvals.values():
            if not future.done():
                future.set_result(False)

    # ── UIAdapter Protocol 구현 ───────────────────────────────────────────────

    async def on_agent_event(self, event: AgentEvent) -> None:
        payload = event.model_dump()
        payload["type"] = getattr(event, "type", "unknown")
        await self._broadcast(payload)

    async def on_stream_text(self, delta: str) -> None:
        await self._broadcast({"type": "stream_delta", "text": delta})

    async def show_error(self, error: str) -> None:
        await self._broadcast({"type": "error", "message": error})

    async def request_approval(self, command: str, reason: str) -> bool:
        """프론트엔드에 승인 요청을 전송하고 사용자 응답까지 대기."""
        approval_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending_approvals[approval_id] = future

        await self._broadcast({
            "type": "approval_request",
            "id": approval_id,
            "command": command[:500],
            "reason": reason,
        })

        try:
            return await asyncio.wait_for(future, timeout=120.0)
        except TimeoutError:
            return False
        finally:
            self._pending_approvals.pop(approval_id, None)

    async def handle_approval_response(self, approval_id: str, approved: bool) -> None:
        future = self._pending_approvals.get(approval_id)
        if future and not future.done():
            future.set_result(approved)

    # ── 내부 유틸 ─────────────────────────────────────────────────────────────

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        dead: set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    @property
    def connected_count(self) -> int:
        return len(self._clients)
