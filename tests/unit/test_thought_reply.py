"""thought 의 짧은 답 분류기: 🔔 답과 음성 승인 답의 프롬프트, verdict 파싱, 실패 fallback 을 검증한다."""

import pytest

from jarvis.agent_layer.thought.reply import (
    FALLBACK,
    TEXT_MAX_CHARS,
    ReplyClassifier,
    build_prompt,
    parse_verdict,
    verdict_schema,
)
from jarvis.agent_layer.thought import reply as reply_mod
from jarvis.model_layer.model_types import ModelConfig
from tests.fixtures.thought_helpers import fake_llm


def classifier(monkeypatch, reply="", error=None, delay=0.0, timeout_sec=1.0):  # type: ignore[no-untyped-def]
    calls = fake_llm(monkeypatch, reply_mod, reply=reply, delay=delay, error=error)
    return ReplyClassifier(ModelConfig(provider="ollama", model="fake"), timeout_sec=timeout_sec), calls


def test_build_prompt_feedback_carries_proposal_and_reply():
    prompt = build_prompt("feedback", "응 그걸로 해줘", "회의 자료를 미리 정리해 둘까요?")
    assert "[비서의 제안] 회의 자료를 미리 정리해 둘까요?" in prompt
    assert "[사용자의 답] 응 그걸로 해줘" in prompt
    assert '"verdict"' in prompt


def test_build_prompt_approval_marks_always_option_and_truncates():
    long = "가" * (TEXT_MAX_CHARS + 50)
    prompt = build_prompt("approval", long, "rm -rf build", has_always=True)
    assert "[실행할 명령] rm -rf build" in prompt
    assert "[항상 허용 선택지] 있음" in prompt
    assert "가" * (TEXT_MAX_CHARS + 1) not in prompt
    assert "[항상 허용 선택지] 없음" in build_prompt("approval", "돌려", "ls")


def test_verdict_schema_lists_kind_verdicts():
    assert verdict_schema("feedback")["properties"]["verdict"]["enum"] == ["accept", "dismiss", "other"]
    assert verdict_schema("approval")["properties"]["verdict"]["enum"] == ["allow", "always", "deny", "unclear"]


@pytest.mark.parametrize(
    ("kind", "raw", "has_always", "want"),
    [
        ("feedback", '{"verdict": "accept"}', False, "accept"),
        ("feedback", '```json\n{"verdict": "DISMISS"}\n```', False, "dismiss"),
        ("feedback", '{"verdict": "maybe"}', False, "other"),
        ("feedback", "그냥 문장", False, "other"),
        ("approval", '{"verdict": "allow"}', False, "allow"),
        ("approval", '{"verdict": "always"}', True, "always"),
        ("approval", '{"verdict": "always"}', False, "allow"),  # 패턴이 없으면 이번 한 번만
        ("approval", '{"verdict": "accept"}', False, "unclear"),  # 피드백 값은 승인에서 모르는 값
        ("approval", "{broken", False, "unclear"),
    ],
)
def test_parse_verdict_normalizes_or_falls_back(kind, raw, has_always, want):
    assert parse_verdict(kind, raw, has_always) == want


async def test_classify_returns_model_verdict(monkeypatch):
    clf, calls = classifier(monkeypatch, reply='{"verdict": "accept"}')

    verdict = await clf.classify("feedback", "응 그걸로 해줘", "자료 정리해 둘까요?")

    assert verdict == "accept"
    assert "자료 정리해 둘까요?" in calls.prompts[0]


@pytest.mark.parametrize(
    ("kind", "error", "delay"),
    [
        ("feedback", RuntimeError("down"), 0.0),
        ("approval", RuntimeError("down"), 0.0),
        ("approval", None, 0.5),
    ],
    ids=["feedback_error", "approval_error", "timeout"],
)
async def test_classify_falls_back_on_error_or_timeout(monkeypatch, kind, error, delay):
    clf, _ = classifier(monkeypatch, reply='{"verdict": "allow"}', error=error, delay=delay, timeout_sec=0.05)

    assert await clf.classify(kind, "그거 돌려", "ls") == FALLBACK[kind]


async def test_classify_blank_text_skips_model(monkeypatch):
    clf, calls = classifier(monkeypatch, reply='{"verdict": "accept"}')

    assert await clf.classify("feedback", "   ") == "other"
    assert calls.prompts == []
