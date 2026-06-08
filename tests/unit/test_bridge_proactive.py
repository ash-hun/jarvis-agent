"""EventBridge 번역 — inner_thought / proactive_message (Tier 0~1 UI 경로)."""

from __future__ import annotations

from jarvis.agent_layer.types import InnerThoughtEvent, ProactiveMessageEvent
from jarvis.ui.tui.bridge import (
    EventBridge,
    InnerThoughtAction,
    ProactiveMessageAction,
)


def test_inner_thought_event_translates_to_action():
    bridge = EventBridge()
    actions = bridge.translate(
        InnerThoughtEvent(session_id="s1", interpretation="속마음", decision="ask", confidence=0.7)
    )
    assert len(actions) == 1
    a = actions[0]
    assert isinstance(a, InnerThoughtAction)
    assert a.interpretation == "속마음"
    assert a.decision == "ask"


def test_proactive_filler_event_translates_with_speak():
    bridge = EventBridge()
    actions = bridge.translate(
        ProactiveMessageEvent(session_id="s1", text="잠깐만요, 확인할게요", kind="filler", speak=True)
    )
    assert len(actions) == 1
    a = actions[0]
    assert isinstance(a, ProactiveMessageAction)
    assert a.text == "잠깐만요, 확인할게요"
    assert a.msg_kind == "filler"
    assert a.speak is True


def test_proactive_message_event_default_kind():
    bridge = EventBridge()
    actions = bridge.translate(ProactiveMessageEvent(session_id="s1", text="먼저 알려드릴 게 있어요"))
    a = actions[0]
    assert isinstance(a, ProactiveMessageAction)
    assert a.msg_kind == "proactive"
    assert a.speak is False
