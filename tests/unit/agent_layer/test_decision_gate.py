"""DecisionGatedEngine: 성찰의 결정과 확신도를 decision model 확률로 바꾸고, 실패하면 원래 프레임을 쓴다."""

import pytest
from datetime import datetime

from jarvis.agent_layer.thought.decision_gate import DecisionGatedEngine, decision_state
from jarvis.agent_layer.thought.thought_types import ThoughtFrame, ThoughtRequest
from jarvis.agent_layer.thought.thought_protocol import ThoughtEngine
from jarvis.model_layer.model_types import ModelConfig, UserMessage

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
        self.states: list[dict] = []

    async def yes_probability(self, state, instructions, no, yes):  # type: ignore[no-untyped-def]
        self.states.append(state)
        return self.p


def engine(frame: ThoughtFrame | None, p: float | None, utterance: str = "회의 5분 전이에요") -> DecisionGatedEngine:
    gate = DecisionGatedEngine(
        FakeInner(frame), FakeDecision(p), ModelConfig(provider="faux", model="m"), clock=lambda: NOW
    )  # type: ignore[arg-type]

    async def fake_utterance(state):  # type: ignore[no-untyped-def]
        return utterance

    gate._utterance = fake_utterance  # type: ignore[method-assign]
    return gate


def reflection(**kw) -> ThoughtRequest:  # type: ignore[no-untyped-def]
    return ThoughtRequest(user_input="(성찰)", mode="reflection", **kw)


async def test_high_probability_speaks_with_probability_as_confidence() -> None:
    frame = ThoughtFrame(decision="silent", confidence=0.1, utterance="")
    out = await engine(frame, 0.82).think(reflection(open_loops=["09:05 회의"]))
    assert out is not None
    assert (out.decision, out.confidence, out.utterance) == ("act", 0.82, "회의 5분 전이에요")


async def test_low_probability_stays_silent_even_if_thought_wanted_to_speak() -> None:
    frame = ThoughtFrame(decision="act", confidence=0.9, utterance="말할게요")
    out = await engine(frame, 0.2).think(reflection())
    assert out is not None and (out.decision, out.confidence, out.utterance) == ("silent", 0.2, "")


async def test_keeps_thought_utterance_when_present() -> None:
    frame = ThoughtFrame(decision="act", confidence=0.4, utterance="디스크가 97%예요")
    out = await engine(frame, 0.7).think(reflection())
    assert out is not None and out.utterance == "디스크가 97%예요"


@pytest.mark.parametrize("p", [None])
async def test_decision_failure_keeps_original_frame(p) -> None:  # type: ignore[no-untyped-def]
    frame = ThoughtFrame(decision="act", confidence=0.9, utterance="말할게요")
    assert await engine(frame, p).think(reflection()) is frame


async def test_request_thought_is_untouched() -> None:
    frame = ThoughtFrame(decision="silent", confidence=0.1)
    gate = engine(frame, 0.99)
    assert await gate.think(ThoughtRequest(user_input="안녕", mode="request")) is frame


def test_state_carries_the_same_material_as_the_thought_prompt() -> None:
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


async def test_ask_from_thought_is_kept_when_speaking() -> None:
    frame = ThoughtFrame(decision="ask", confidence=0.4, utterance="지금 정리해 드릴까요?")
    out = await engine(frame, 0.9).think(reflection())
    assert out is not None and out.decision == "ask"


def test_decision_model_uses_its_own_threshold() -> None:
    from jarvis.jarvis_config import ProactiveConfig

    assert ProactiveConfig().effective_threshold() == 0.85
    assert ProactiveConfig(decision_model="tev1").effective_threshold() == 0.6


async def test_nothing_to_tell_stays_silent_even_with_high_probability() -> None:
    frame = ThoughtFrame(decision="silent", confidence=0.1, utterance="")
    out = await engine(frame, 0.9, utterance="").think(reflection())
    assert out is not None and (out.decision, out.utterance) == ("silent", "")


async def test_utterance_prompt_carries_persona_and_allows_nothing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from jarvis.model_layer.model_types import AssistantMessage
    from jarvis.agent_layer.thought import decision_gate

    prompts: list[str] = []

    async def fake_stream(model, ctx, options):  # type: ignore[no-untyped-def]
        prompts.append(ctx.messages[0].content)
        return AssistantMessage(content=[])

    monkeypatch.setattr(decision_gate, "stream_to_message", fake_stream)
    gate = DecisionGatedEngine(
        FakeInner(ThoughtFrame(decision="silent", confidence=0.1)),
        FakeDecision(0.9),  # type: ignore[arg-type]
        ModelConfig(provider="faux", model="m"),
        clock=lambda: NOW,
        persona="애쉬의 행정비서",
    )
    out = await gate.think(reflection())
    assert "[말투] 애쉬의 행정비서" in prompts[0] and "아무것도 출력하지 않는다" in prompts[0]
    assert out is not None and out.decision == "silent"
