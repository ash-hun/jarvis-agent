"""PerConnectionAdapter — Web HUD WebSocket 어댑터 단위 명세.

approval Future 왕복 패턴이 가장 깨지기 쉬운 부분이라 집중 커버한다.
실 WebSocket 없이 FakeWebSocket으로 검증(전송 페이로드만 기록)."""

from __future__ import annotations

import asyncio

import pytest

from jarvis.agent_layer.types import MessageUpdateEvent
from jarvis.ui.web.adapter import PerConnectionAdapter


class FakeWebSocket:
    """send_json 호출 페이로드를 순서대로 기록하는 가짜 WebSocket."""

    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[dict] = []
        self._fail = fail

    async def send_json(self, payload: dict) -> None:
        if self._fail:
            raise RuntimeError("socket closed")
        self.sent.append(payload)


# ── 이벤트/스트림/에러 전송 ──────────────────────────────────────────────────


async def test_on_agent_event_serializes_and_tags_type():
    ws = FakeWebSocket()
    adapter = PerConnectionAdapter(ws)

    await adapter.on_agent_event(MessageUpdateEvent(text_delta="hi"))

    assert len(ws.sent) == 1
    assert ws.sent[0]["type"] == "message_update"
    assert ws.sent[0]["text_delta"] == "hi"


async def test_on_stream_text_emits_delta():
    ws = FakeWebSocket()
    adapter = PerConnectionAdapter(ws)

    await adapter.on_stream_text("조각")

    assert ws.sent == [{"type": "stream_delta", "text": "조각"}]


async def test_show_error_emits_error():
    ws = FakeWebSocket()
    adapter = PerConnectionAdapter(ws)

    await adapter.show_error("터졌다")

    assert ws.sent == [{"type": "error", "message": "터졌다"}]


async def test_send_failure_is_swallowed():
    """전송 실패(연결 끊김)는 예외로 전파되지 않는다 — 메인 턴을 막지 않음."""
    ws = FakeWebSocket(fail=True)
    adapter = PerConnectionAdapter(ws)

    # 어느 것도 raise하지 않아야 한다
    await adapter.on_agent_event(MessageUpdateEvent(text_delta="x"))
    await adapter.on_stream_text("x")
    await adapter.show_error("y")


# ── approval Future 왕복 ─────────────────────────────────────────────────────


async def test_request_approval_resolves_on_response():
    """request_approval은 handle_approval_response가 올 때까지 블록하고, 그 값을 돌린다."""
    ws = FakeWebSocket()
    adapter = PerConnectionAdapter(ws)

    task = asyncio.ensure_future(adapter.request_approval("rm -rf /", "위험"))
    await asyncio.sleep(0)  # request_approval이 approval_request를 보내도록 양보

    assert len(ws.sent) == 1
    req = ws.sent[0]
    assert req["type"] == "approval_request"
    assert req["command"] == "rm -rf /"
    approval_id = req["id"]
    assert not task.done()  # 아직 응답 전 — 블록 중

    await adapter.handle_approval_response(approval_id, approved=True)
    assert await asyncio.wait_for(task, timeout=1.0) is True


async def test_request_approval_returns_denied():
    ws = FakeWebSocket()
    adapter = PerConnectionAdapter(ws)

    task = asyncio.ensure_future(adapter.request_approval("cmd", "이유"))
    await asyncio.sleep(0)
    approval_id = ws.sent[0]["id"]

    await adapter.handle_approval_response(approval_id, approved=False)
    assert await asyncio.wait_for(task, timeout=1.0) is False


async def test_request_approval_command_truncated_to_500():
    ws = FakeWebSocket()
    adapter = PerConnectionAdapter(ws)

    asyncio.ensure_future(adapter.request_approval("x" * 1000, "이유"))
    await asyncio.sleep(0)

    assert len(ws.sent[0]["command"]) == 500


async def test_request_approval_returns_false_on_send_failure():
    """approval_request 전송 실패 시 즉시 False(거부)로 처리하고 펜딩을 정리한다."""
    ws = FakeWebSocket(fail=True)
    adapter = PerConnectionAdapter(ws)

    assert await adapter.request_approval("cmd", "이유") is False
    assert adapter._pending_approvals == {}


async def test_handle_unknown_approval_id_is_noop():
    """알 수 없는 approval_id 응답은 조용히 무시(크래시 없음)."""
    ws = FakeWebSocket()
    adapter = PerConnectionAdapter(ws)

    await adapter.handle_approval_response("does-not-exist", approved=True)  # no raise


@pytest.mark.parametrize("approved", [True, False])
async def test_pending_cleared_after_resolution(approved: bool):
    ws = FakeWebSocket()
    adapter = PerConnectionAdapter(ws)

    task = asyncio.ensure_future(adapter.request_approval("cmd", "이유"))
    await asyncio.sleep(0)
    approval_id = ws.sent[0]["id"]
    await adapter.handle_approval_response(approval_id, approved=approved)
    await asyncio.wait_for(task, timeout=1.0)

    assert adapter._pending_approvals == {}
