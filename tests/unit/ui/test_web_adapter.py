"""PerConnectionAdapter 를 실 WebSocket 없이 FakeWebSocket 으로 검증한다."""

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
