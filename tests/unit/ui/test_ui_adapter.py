"""UIAdapter 기본 동작: 이벤트, 스트림, 오류는 버리고 승인은 거절한다. 구현체는 이를 물려받는다."""

from jarvis.agent_layer.types import AgentStartEvent
from jarvis.ui.protocol import UIAdapter
from jarvis.ui.web.adapter import PerConnectionAdapter
from jarvis.ui.web.approvals import Connection


async def test_defaults_are_noops_and_deny_approval():
    adapter = UIAdapter()
    assert await adapter.on_agent_event(AgentStartEvent(session_id="s", prompt="p")) is None
    assert await adapter.on_stream_text("x") is None
    assert await adapter.show_error("boom") is None
    assert await adapter.request_approval("rm -rf /", "danger") is False


async def test_connection_default_send_is_noop():
    assert await Connection().send({"type": "x"}) is None


def test_implementations_inherit_bases():
    assert issubclass(PerConnectionAdapter, UIAdapter)
    assert issubclass(PerConnectionAdapter, Connection)
    from jarvis.ui.tui.app import JarvisTUI

    assert issubclass(JarvisTUI, UIAdapter)
