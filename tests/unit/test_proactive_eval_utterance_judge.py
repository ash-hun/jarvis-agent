"""proactive_eval 의 utterance_judge: 판정자 출력을 스키마로 검증하고, 근거 구간을 확인하고, 라벨별 일치율을 잰다."""

from jarvis.core.proactive.eval.utterance_judge import UtteranceJudge, agreement_by_label, parse_verdict
from jarvis.core.proactive.eval import utterance_judge
from jarvis.model_layer.model_types import ModelConfig
from tests.fixtures.thought_helpers import fake_llm

UTTERANCE = "10시 자동이체에 잔액이 모자라요"


def test_parse_verdict_checks_evidence_span() -> None:
    ok = parse_verdict('{"label": "concrete_notice", "evidence": "잔액이 모자라요"}', UTTERANCE)
    made_up = parse_verdict('```json\n{"label": "concrete_notice", "evidence": "카드값"}\n```', UTTERANCE)

    assert ok is not None and ok.evidence_found
    assert made_up is not None and not made_up.evidence_found


def test_parse_verdict_rejects_unknown_label_and_garbage() -> None:
    assert parse_verdict('{"label": "nice", "evidence": ""}', UTTERANCE) is None
    assert parse_verdict("모르겠다", UTTERANCE) is None


def test_agreement_by_label() -> None:
    out = agreement_by_label(
        ["greeting_only", "greeting_only", "concrete_notice"], ["greeting_only", None, "concrete_notice"]
    )

    assert out == {"greeting_only": 0.5, "concrete_notice": 1.0, "all": 2 / 3}
    assert agreement_by_label([], []) == {}


async def test_judge_sends_only_utterance_and_last_answer(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls = fake_llm(monkeypatch, utterance_judge, reply='{"label": "greeting_only", "evidence": "안녕하세요"}')

    verdict = await UtteranceJudge(ModelConfig(provider="faux", model="m")).judge("안녕하세요!", "직전 답")

    assert verdict is not None and verdict.label == "greeting_only" and verdict.evidence_found
    assert "[직전 답] 직전 답" in calls.prompts[0]


async def test_judge_returns_none_on_empty_reply(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake_llm(monkeypatch, utterance_judge, reply="")

    assert await UtteranceJudge(ModelConfig(provider="faux", model="m")).judge("안녕") is None
