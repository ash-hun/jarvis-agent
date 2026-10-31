"""thought 의 DecisionGatedEngine: 성찰의 결정과 확신도를 decision model 확률로 바꾸고, 실패하면 원래 프레임을 쓴다."""

import pytest
from datetime import datetime

from jarvis.agent_layer.thought.decision_gate import DecisionGatedEngine, decision_state
from jarvis.agent_layer.thought.thought_types import ThoughtFrame, ThoughtRequest
from jarvis.agent_layer.thought.thought_protocol import ThoughtEngine
from jarvis.model_layer.model_types import ModelConfig, UserMessage
from jarvis.agent_layer.thought import decision_gate
from tests.fixtures.thought_helpers import fake_llm
from jarvis.jarvis_config import ProactiveConfig

NOW = datetime(2026, 1, 1, 9, 0)


class FakeInner(ThoughtEngine):
    def __init__(self, frame: ThoughtFrame | None) -> None:
        self.frame = frame

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        return self.frame


class FakeDecision:
    model = "fake-decision"

    def __init__(self, p: float | None) -> None:
        self.p = p

    async def yes_probability(self, state, instructions, no, yes):  # type: ignore[no-untyped-def]
        return self.p


def engine(frame: ThoughtFrame | None, p: float | None, persona: str = "") -> DecisionGatedEngine:
    return DecisionGatedEngine(
        FakeInner(frame),
        FakeDecision(p),  # type: ignore[arg-type]
        ModelConfig(provider="faux", model="m"),
        clock=lambda: NOW,
        persona=persona,
    )


def reflection(**kw) -> ThoughtRequest:  # type: ignore[no-untyped-def]
    return ThoughtRequest(user_input="(성찰)", mode="reflection", **kw)


@pytest.mark.parametrize(
    ("decision", "utterance", "p", "generated", "expected"),
    [
        ("silent", "", 0.82, "회의 5분 전이에요", ("act", 0.82, "회의 5분 전이에요")),
        ("act", "말할게요", 0.2, "", ("silent", 0.2, "")),
        ("act", "디스크가 97%예요", 0.7, "다른 말", ("act", 0.7, "디스크가 97%예요")),
        ("ask", "지금 정리해 드릴까요?", 0.9, "", ("ask", 0.9, "지금 정리해 드릴까요?")),
        ("silent", "", 0.9, "", ("silent", 0.9, "")),
    ],
    ids=["high_p_speaks", "low_p_silent", "keeps_thought_utterance", "keeps_ask", "nothing_to_tell_silent"],
)
async def test_think_gates_reflection_by_probability(monkeypatch, decision, utterance, p, generated, expected) -> None:  # type: ignore[no-untyped-def]
    fake_llm(monkeypatch, decision_gate, reply=generated)
    frame = ThoughtFrame(decision=decision, confidence=0.1, utterance=utterance)

    out = await engine(frame, p).think(reflection(open_loops=["09:05 회의"]))

    assert out is not None
    assert (out.decision, out.confidence, out.utterance) == expected


@pytest.mark.parametrize(
    ("mode", "p"), [("reflection", None), ("request", 0.99)], ids=["decision_failure", "request_thought"]
)
async def test_think_keeps_original_frame_when_not_gated(mode, p) -> None:  # type: ignore[no-untyped-def]
    frame = ThoughtFrame(decision="act", confidence=0.9, utterance="말할게요")

    out = await engine(frame, p).think(ThoughtRequest(user_input="안녕", mode=mode))

    assert out is frame


def test_decision_state_carries_the_same_material_as_the_thought_prompt() -> None:
    req = reflection(
        history=[UserMessage(content="9시 5분 회의")],
        open_loops=["회의"],
        external_events=["[calendar] 5분 전"],
        recent_proactive=["회의 곧이에요"],
    )

    state = decision_state(req, NOW)

    assert state == {
        "now": "2026-01-01T09:00",
        "recent_conversation": ["user: 9시 5분 회의"],
        "open_promises": ["회의"],
        "external_events": ["[calendar] 5분 전"],
        "already_said_recently": ["회의 곧이에요"],
    }


def test_effective_threshold_uses_decision_threshold_with_decision_model() -> None:
    assert ProactiveConfig().effective_threshold() == 0.85
    assert ProactiveConfig(decision_model="tev1").effective_threshold() == 0.6


async def test_think_utterance_prompt_carries_persona_and_allows_nothing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls = fake_llm(monkeypatch, decision_gate, reply="")
    gate = engine(ThoughtFrame(decision="silent", confidence=0.1), 0.9, persona="애쉬의 행정비서")

    out = await gate.think(reflection())

    assert "[말투] 애쉬의 행정비서" in calls.prompts[0] and "아무것도 출력하지 않는다" in calls.prompts[0]
    assert out is not None and out.decision == "silent"
