"""[agent_layer] 🔔 짧은 답과 음성 승인 답 분류기(프롬프트, verdict 파싱, 실패 fallback) 테스트."""

import asyncio

import pytest

from jarvis.agent_layer.thought.reply import (
    FALLBACK,
    TEXT_MAX_CHARS,
    ReplyClassifier,
    build_prompt,
    parse_verdict,
    verdict_schema,
)
from jarvis.model_layer.types import ModelConfig


class FakeClassifier(ReplyClassifier):
    """모델 호출만 바꾼다. 받은 프롬프트를 남긴다."""

    def __init__(self, reply=None, error=None, delay=0.0, timeout_sec=1.0):
        super().__init__(ModelConfig(provider="ollama", model="fake"), timeout_sec=timeout_sec)
        self._reply, self._error, self._delay = reply, error, delay
        self.prompts: list[str] = []

    async def _call_model(self, prompt, kind):
        self.prompts.append(prompt)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error:
            raise self._error
        return self._reply


def test_feedback_prompt_carries_proposal_and_reply():
    prompt = build_prompt("feedback", "응 그걸로 해줘", "회의 자료를 미리 정리해 둘까요?")
    assert "[비서의 제안] 회의 자료를 미리 정리해 둘까요?" in prompt
    assert "[사용자의 답] 응 그걸로 해줘" in prompt
    assert '"verdict"' in prompt


def test_approval_prompt_marks_always_option_and_truncates():
    long = "가" * (TEXT_MAX_CHARS + 50)
    prompt = build_prompt("approval", long, "rm -rf build", has_always=True)
    assert "[실행할 명령] rm -rf build" in prompt
    assert "[항상 허용 선택지] 있음" in prompt
    assert "가" * (TEXT_MAX_CHARS + 1) not in prompt
    assert "[항상 허용 선택지] 없음" in build_prompt("approval", "돌려", "ls")


def test_verdict_schema_enums():
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
def test_parse_verdict(kind, raw, has_always, want):
    assert parse_verdict(kind, raw, has_always) == want


async def test_classify_returns_model_verdict():
    clf = FakeClassifier(reply='{"verdict": "accept"}')
    assert await clf.classify("feedback", "응 그걸로 해줘", "자료 정리해 둘까요?") == "accept"
    assert "자료 정리해 둘까요?" in clf.prompts[0]


@pytest.mark.parametrize("kind", ["feedback", "approval"])
async def test_classify_falls_back_on_error(kind):
    assert await FakeClassifier(error=RuntimeError("down")).classify(kind, "그거 돌려") == FALLBACK[kind]


async def test_classify_falls_back_on_timeout():
    clf = FakeClassifier(reply='{"verdict": "allow"}', delay=0.5, timeout_sec=0.05)
    assert await clf.classify("approval", "그거 돌려", "ls") == "unclear"


async def test_blank_text_skips_model():
    clf = FakeClassifier(reply='{"verdict": "accept"}')
    assert await clf.classify("feedback", "   ") == "other"
    assert clf.prompts == []
