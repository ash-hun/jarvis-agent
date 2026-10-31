"""web_hud 의 PerConnectionAdapter: 이벤트를 연결 하나로 보내고 끊긴 연결의 전송 실패는 삼키는지 검증한다."""

import pytest

from jarvis.agent_layer.agent_types import MessageUpdateEvent
from jarvis.ui.web.adapter import PerConnectionAdapter
from jarvis.ui.web.approvals import Connection


class FakeWebSocket:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[dict] = []
        self._fail = fail

    async def send_json(self, payload: dict) -> None:
        if self._fail:
            raise RuntimeError("socket closed")
        self.sent.append(payload)


@pytest.mark.parametrize(
    ("method", "arg", "expected"),
    [
        ("on_agent_event", MessageUpdateEvent(text_delta="hi"), {"type": "message_update", "text_delta": "hi"}),
        ("on_stream_text", "조각", {"type": "stream_delta", "text": "조각"}),
        ("show_error", "터졌다", {"type": "error", "message": "터졌다"}),
    ],
)
async def test_adapter_sends_one_typed_payload(method, arg, expected):
    ws = FakeWebSocket()

    await getattr(PerConnectionAdapter(ws), method)(arg)

    assert len(ws.sent) == 1
    assert expected.items() <= ws.sent[0].items()


async def test_send_failure_is_swallowed():
    """전송 실패(연결 끊김)는 예외로 전파되지 않는다. 메인 턴을 막지 않는다."""
    adapter = PerConnectionAdapter(FakeWebSocket(fail=True))

    await adapter.on_agent_event(MessageUpdateEvent(text_delta="x"))
    await adapter.on_stream_text("x")
    await adapter.show_error("y")


async def test_adapter_is_a_connection_whose_base_send_is_noop():
    assert issubclass(PerConnectionAdapter, Connection)
    assert await Connection().send({"type": "x"}) is None
