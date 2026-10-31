"""memory 기능의 컴팩션 요약기: 메시지 렌더, 이전 요약 이어 쓰기, 실패와 빈 응답, 대화 언어 따라가기."""

import pytest

from jarvis.memory.consolidation.compaction import (
    conversation_language,
    llm_summarizer,
    render_messages,
    summarize_messages,
    system_prompt_for,
)
from jarvis.model_layer.model_types import AssistantMessage, LLMContext, TextContent, UserMessage


def test_render_messages_tags_role_and_serializes_blocks():
    text = render_messages([UserMessage(content="안녕"), AssistantMessage(content=[TextContent(text="네")])])

    first, second = text.split("\n")
    assert first == "[user] 안녕"
    assert second.startswith("[assistant] {") and '"네"' in second


async def test_summarize_messages_continues_prior_summary(monkeypatch, faux_model):
    seen: list[LLMContext] = []

    async def fake_stream(model, ctx, options):
        seen.append(ctx)
        return AssistantMessage(content=[TextContent(text="  새 요약  ")])

    monkeypatch.setattr("jarvis.model_layer.stream.stream_to_message", fake_stream)

    summary = await summarize_messages(faux_model, [UserMessage(content="hi")], prior="옛 요약")

    assert summary == "새 요약"
    prompt = seen[0].messages[0].content
    assert isinstance(prompt, str) and prompt.startswith("이전 요약:\n옛 요약\n\n") and "[user] hi" in prompt
    assert seen[0].system_prompt == system_prompt_for([UserMessage(content="hi")])


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (AssistantMessage(content=[], error_message="boom"), None),
        (AssistantMessage(content=[TextContent(text="   ")]), "[summary unavailable]"),
    ],
    ids=["model_error", "blank_reply"],
)
async def test_llm_summarizer_none_on_error_and_placeholder_on_blank(monkeypatch, faux_model, reply, expected):
    async def fake_stream(model, ctx, options):
        return reply

    monkeypatch.setattr("jarvis.model_layer.stream.stream_to_message", fake_stream)

    assert await llm_summarizer(faux_model)([UserMessage(content="hi")], None) == expected


def test_summary_language_follows_conversation_text():
    ko = [UserMessage(content="예산은 1200만원이야"), AssistantMessage(content=[TextContent(text="알겠습니다")])]
    en = [UserMessage(content="The budget is $40k"), AssistantMessage(content=[TextContent(text="Got it")])]

    # 어시스턴트 메시지의 JSON 키는 세지 않는다
    assert conversation_language(ko) == "ko"
    assert conversation_language(en) == "en"
    # 코드와 영어 낱말이 많은 한국어 개발 대화도 한국어다
    assert conversation_language([UserMessage(content="pytest 로 tests/unit/test_api.py 돌려줘")]) == "ko"
    assert "한국어로 쓴다" in system_prompt_for(ko)
    assert "English" in system_prompt_for(en)
