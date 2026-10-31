"""agent_loop: 루프 시작과 끝 이벤트가 agent_name 을 싣고, 주지 않으면 None 인지 검증한다."""

import pytest

from jarvis.agent_layer.agent_types import AgentEndEvent, AgentStartEvent


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (AgentStartEvent(session_id="s1", prompt="hi", agent_name="researcher"), "researcher"),
        (AgentStartEvent(session_id="s1", prompt="hi"), None),
        (AgentEndEvent(session_id="s1", agent_name="writer"), "writer"),
        (AgentEndEvent(session_id="s1"), None),
    ],
)
def test_lifecycle_event_carries_agent_name(event, expected):
    assert event.agent_name == expected
