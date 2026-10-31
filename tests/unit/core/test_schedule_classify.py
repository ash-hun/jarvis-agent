"""스케줄 등록 분류기: LLM 답에 TASK 가 있으면 task, 그 밖(실패, 시간 초과 포함)은 reminder."""

import pytest
import asyncio

from jarvis.model_layer.model_types import AssistantMessage, ModelConfig, TextContent
from jarvis.core.scheduler.classify import make_llm_classifier

MODEL = ModelConfig(provider="faux", model="faux-model")


def _patch_llm(monkeypatch, reply=None, error=None, delay=0.0):
    prompts: list[str] = []

    async def fake_stream(model, ctx, options):
        prompts.append(ctx.messages[0].content)
        if delay:
            await asyncio.sleep(delay)
        if error is not None:
            raise error
        return AssistantMessage(content=[TextContent(text=reply or "")])

    monkeypatch.setattr("jarvis.model_layer.stream.stream_to_message", fake_stream)
    return prompts


@pytest.mark.parametrize(
    ("reply", "kind"),
    [("TASK", "task"), ("task.", "task"), ("REMINDER", "reminder"), ("", "reminder"), ("모르겠다", "reminder")],
)
async def test_classifier_maps_reply_to_kind(monkeypatch, reply, kind):
    prompts = _patch_llm(monkeypatch, reply=reply)
    assert await make_llm_classifier(MODEL)("오늘 뉴스 요약해줘") == kind
    assert "항목: 오늘 뉴스 요약해줘" in prompts[0]


async def test_classifier_falls_back_to_reminder_on_error(monkeypatch):
    _patch_llm(monkeypatch, error=RuntimeError("llm down"))
    assert await make_llm_classifier(MODEL)("물 마시기") == "reminder"


async def test_classifier_falls_back_to_reminder_on_timeout(monkeypatch):
    _patch_llm(monkeypatch, reply="TASK", delay=1.0)
    assert await make_llm_classifier(MODEL, timeout=0.01)("물 마시기") == "reminder"
