"""tui: EventBridge 가 루프 시작과 끝, inner_thought, proactive_message 이벤트를 화면 액션으로 옮기는지 검증한다."""

import pytest

from jarvis.ui.tui.bridge import (
    AgentPopAction,
    AgentPushAction,
    EventBridge,
    InnerThoughtAction,
    ProactiveMessageAction,
)
from jarvis.agent_layer.agent_types import AgentEndEvent, AgentStartEvent, InnerThoughtEvent, ProactiveMessageEvent


@pytest.mark.parametrize(("agent_name", "shown"), [("planner", "planner"), (None, "agent")])
def test_agent_start_becomes_single_push_with_name_or_fallback(agent_name, shown):
    actions = EventBridge().translate(AgentStartEvent(session_id="s", prompt="", agent_name=agent_name))

    assert len(actions) == 1
    assert isinstance(actions[0], AgentPushAction)
    assert actions[0].agent_name == shown


def test_agent_end_flushes_stream_and_pops_same_agent():
    actions = EventBridge().translate(AgentEndEvent(session_id="s", agent_name="executor"))

    kinds = [a.kind for a in actions]
    assert "flush_stream" in kinds and "agent_pop" in kinds
    pop = next(a for a in actions if isinstance(a, AgentPopAction))
    assert pop.agent_name == "executor"


def test_translate_inner_thought_event_to_action():
    event = InnerThoughtEvent(session_id="s1", interpretation="속마음", decision="ask", confidence=0.7)

    actions = EventBridge().translate(event)

    assert len(actions) == 1
    assert isinstance(actions[0], InnerThoughtAction)
    assert (actions[0].interpretation, actions[0].decision) == ("속마음", "ask")


@pytest.mark.parametrize(
    ("event", "msg_kind", "speak"),
    [
        (ProactiveMessageEvent(session_id="s1", text="잠깐만요", kind="filler", speak=True), "filler", True),
        (ProactiveMessageEvent(session_id="s1", text="먼저 알려드릴 게 있어요"), "proactive", False),
    ],
)
def test_translate_proactive_message_keeps_kind_and_speak(event, msg_kind, speak):
    actions = EventBridge().translate(event)

    assert len(actions) == 1
    assert isinstance(actions[0], ProactiveMessageAction)
    assert (actions[0].text, actions[0].msg_kind, actions[0].speak) == (event.text, msg_kind, speak)
