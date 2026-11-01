"""thought 의 DecisionGatedEngine: decision model 을 먼저 묻고, 문턱 아래면 사고를 건너뛰고, 앵커 없는 말은 막는다."""

import pytest
from typing import Any
from datetime import datetime

from jarvis.agent_layer.thought.decision_gate import (
    DecisionGatedEngine,
    candidate_items,
    decision_state,
    gated_confidence,
)
from jarvis.agent_layer.thought.thought_types import SituationFact, ThoughtFrame, ThoughtRequest
from jarvis.agent_layer.thought.thought_protocol import ThoughtEngine
from jarvis.model_layer.model_types import ModelConfig, UserMessage
from jarvis.agent_layer.thought import decision_gate
from tests.fixtures.thought_helpers import fake_llm
from jarvis.jarvis_config import ProactiveConfig

NOW = datetime(2026, 1, 1, 9, 0)


class FakeInner(ThoughtEngine):
    def __init__(self, frame: ThoughtFrame | None) -> None:
        self.frame = frame
        self.requests: list[ThoughtRequest] = []

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        self.requests.append(request)
        return self.frame


class FakeDecision:
    model = "fake-decision"

    def __init__(self, p: float | None, items: dict[str, float] | None = None) -> None:
        self.p = p
        self.items = items or {}
        self.states: list[dict[str, Any]] = []

    async def yes_probability(self, state, instructions, no, yes):  # type: ignore[no-untyped-def]
        self.states.append(state)
        if "focus_item" not in state:
            return self.p
        item = state["focus_item"]
        text = item["item"] if isinstance(item, dict) else item
        return self.items.get(text, self.p)


def engine(frame: ThoughtFrame | None, decision: FakeDecision, **kw: Any) -> tuple[DecisionGatedEngine, FakeInner]:
    inner = FakeInner(frame)
    gate = DecisionGatedEngine(
        inner,
        decision,  # type: ignore[arg-type]
        ModelConfig(provider="faux", model="m"),
        clock=lambda: NOW,
        **kw,
    )
    return gate, inner


def reflection(**kw) -> ThoughtRequest:  # type: ignore[no-untyped-def]
    return ThoughtRequest(user_input="(성찰)", mode="reflection", **kw)


@pytest.mark.parametrize(
    ("decision", "utterance", "p", "generated", "expected"),
    [
        ("silent", "", 0.82, "회의 5분 전이에요", ("act", 0.82, "회의 5분 전이에요")),
        ("act", "말할게요", 0.2, "", ("silent", 0.2, "")),
        ("act", "회의실 디스크가 97%예요", 0.7, "다른 말", ("act", 0.7, "회의실 디스크가 97%예요")),
        ("ask", "회의 자료 정리해 드릴까요?", 0.9, "", ("ask", 0.9, "회의 자료 정리해 드릴까요?")),
        ("silent", "", 0.9, "", ("silent", 0.9, "")),
    ],
    ids=["high_p_speaks", "low_p_silent", "keeps_thought_utterance", "keeps_ask", "nothing_to_tell_silent"],
)
async def test_think_gates_reflection_by_probability(monkeypatch, decision, utterance, p, generated, expected) -> None:  # type: ignore[no-untyped-def]
    fake_llm(monkeypatch, decision_gate, reply=generated)
    frame = ThoughtFrame(decision=decision, confidence=0.1, utterance=utterance)
    gate, _ = engine(frame, FakeDecision(p))

    out = await gate.think(reflection(open_loops=["09:05 회의"]))

    assert out is not None
    assert (out.decision, out.confidence, out.utterance) == expected


@pytest.mark.parametrize(
    ("mode", "p"), [("reflection", None), ("request", 0.99)], ids=["decision_failure", "request_thought"]
)
async def test_think_keeps_original_frame_when_not_gated(mode, p) -> None:  # type: ignore[no-untyped-def]
    frame = ThoughtFrame(decision="act", confidence=0.9, utterance="말할게요")
    gate, _ = engine(frame, FakeDecision(p))

    out = await gate.think(ThoughtRequest(user_input="안녕", mode=mode))

    assert out is frame


async def test_think_below_floor_skips_thought_and_item_questions() -> None:
    decision = FakeDecision(0.1)
    gate, inner = engine(ThoughtFrame(decision="act", utterance="회의"), decision)

    out = await gate.think(reflection(open_loops=["09:05 회의"], external_events=["[ci] 실패"]))

    assert out is not None and out.decision == "silent" and out.confidence == 0.1
    assert inner.requests == [] and len(decision.states) == 1


async def test_think_anchors_on_most_probable_item_and_takes_the_smaller_probability() -> None:
    facts = [SituationFact(text="[ad] 할인 쿠폰"), SituationFact(text="[bank] 잔액 부족 10:00", minutes=60)]
    decision = FakeDecision(0.9, {"[ad] 할인 쿠폰": 0.1, "[bank] 잔액 부족 10:00": 0.7})
    gate, inner = engine(ThoughtFrame(decision="act", utterance="10시 자동이체 잔액이 모자라요"), decision)

    out = await gate.think(reflection(external_events=[f.text for f in facts], facts=facts))

    assert out is not None and (out.decision, out.confidence) == ("act", 0.7)
    assert inner.requests[0].anchor == "[bank] 잔액 부족 10:00"
    assert decision.states[0]["computed_facts"][1]["time_left"] == "1시간 뒤"


async def test_think_silences_utterance_missing_the_anchor() -> None:
    gate, _ = engine(ThoughtFrame(decision="act", utterance="안녕하세요! 궁금한 점 있으세요?"), FakeDecision(0.9))

    out = await gate.think(reflection(external_events=["[bank] 잔액 부족 10:00"]))

    assert out is not None and out.decision == "silent" and out.utterance == ""
    assert "anchor missing" in out.rationale


async def test_think_decision_first_only_asks_once_and_keeps_utterance() -> None:
    decision = FakeDecision(0.8)
    gate, inner = engine(ThoughtFrame(decision="act", utterance="안녕하세요"), decision, anchor=False, facts=False)

    out = await gate.think(reflection(external_events=["[bank] 잔액 부족"]))

    assert out is not None and (out.decision, out.utterance) == ("act", "안녕하세요")
    assert len(decision.states) == 1 and inner.requests[0].anchor == ""


async def test_think_caps_item_questions() -> None:
    decision = FakeDecision(0.8)
    gate, _ = engine(ThoughtFrame(decision="act", utterance="a 1"), decision, max_item_questions=2)

    await gate.think(reflection(external_events=["a 1", "b 2", "c 3", "d 4"]))

    assert len(decision.states) == 1 + 2


def test_candidate_items_put_urgent_unhandled_first() -> None:
    facts = [
        SituationFact(text="done", minutes=5, signal="완료"),
        SituationFact(text="far", days=14),
        SituationFact(text="unknown"),
        SituationFact(text="soon", minutes=20),
    ]

    picked = candidate_items(reflection(facts=facts), with_facts=True, limit=3)

    assert [f.text for f in picked] == ["soon", "unknown", "far"]


def test_candidate_items_without_facts_use_text_order() -> None:
    picked = candidate_items(reflection(open_loops=["l"], external_events=["e1", "e2"]), with_facts=False, limit=2)

    assert [f.text for f in picked] == ["l", "e1"]


@pytest.mark.parametrize(
    ("p", "items", "facts", "expected"),
    [(0.9, [0.2, 0.6], True, 0.6), (0.4, [0.9], True, 0.4), (0.9, [0.1], False, 0.9), (0.7, [], True, 0.7)],
    ids=["item_lower", "overall_lower", "anchor_only_keeps_p", "no_items"],
)
def test_gated_confidence(p, items, facts, expected) -> None:  # type: ignore[no-untyped-def]
    assert gated_confidence(p, items, facts) == expected


def test_decision_state_carries_the_same_material_as_the_thought_prompt() -> None:
    req = reflection(
        history=[UserMessage(content="9시 5분 회의")],
        open_loops=["회의"],
        external_events=["[calendar] 5분 전"],
        recent_proactive=["회의 곧이에요"],
        facts=[SituationFact(text="회의", minutes=5)],
    )

    assert decision_state(req, NOW) == {
        "now": "2026-01-01T09:00",
        "recent_conversation": ["user: 9시 5분 회의"],
        "open_promises": ["회의"],
        "external_events": ["[calendar] 5분 전"],
        "already_said_recently": ["회의 곧이에요"],
    }
    assert decision_state(req, NOW, with_facts=True)["computed_facts"] == [
        {"item": "회의", "time_left": "5분 뒤", "within_30_min": True, "handled_signal": "none"}
    ]


def test_effective_threshold_uses_decision_threshold_with_decision_model() -> None:
    assert ProactiveConfig().effective_threshold() == 0.85
    assert ProactiveConfig(decision_model="tev1").effective_threshold() == 0.6


async def test_think_utterance_prompt_carries_persona_anchor_and_allows_nothing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls = fake_llm(monkeypatch, decision_gate, reply="")
    gate, _ = engine(ThoughtFrame(decision="silent", confidence=0.1), FakeDecision(0.9), persona="애쉬의 행정비서")

    out = await gate.think(reflection(external_events=["[ci] 빌드 실패"]))

    assert "[말투] 애쉬의 행정비서" in calls.prompts[0] and "아무것도 출력하지 않는다" in calls.prompts[0]
    assert "[먼저 꺼낼 항목] [ci] 빌드 실패" in calls.prompts[0]
    assert out is not None and out.decision == "silent"
