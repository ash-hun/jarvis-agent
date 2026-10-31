"""tui 의 UIAdapter 기본 클래스: 이벤트는 버리고 승인은 거절하며, 화면 구현체가 물려받는지 검증한다."""

from jarvis.agent_layer.agent_types import AgentStartEvent
from jarvis.ui.web.adapter import PerConnectionAdapter
from jarvis.ui.ui_protocol import UIAdapter
from jarvis.ui.tui.app import JarvisTUI


async def test_defaults_are_noops_and_deny_approval():
    adapter = UIAdapter()

    assert await adapter.on_agent_event(AgentStartEvent(session_id="s", prompt="p")) is None
    assert await adapter.on_stream_text("x") is None
    assert await adapter.show_error("boom") is None
    assert await adapter.request_approval("rm -rf /", "danger") is False


def test_screen_adapters_inherit_the_base():
    assert issubclass(PerConnectionAdapter, UIAdapter)
    assert issubclass(JarvisTUI, UIAdapter)
