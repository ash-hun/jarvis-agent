"""memory: 질문에서 기억으로 찾을 대상을 뽑는 추출기가 답을 읽고 실패를 빈 목록으로 돌리는지 검증."""

import pytest

from jarvis.memory.retrieval.coverage_extract import MAX_ENTITIES, llm_entity_extractor, parse_entities
from jarvis.model_layer.model_types import AssistantMessage, ModelConfig, TextContent
from jarvis.model_layer import stream as stream_mod

MODEL = ModelConfig(provider="openai", model="gpt-4o-mini")


def test_parse_entities_dedupes_and_caps():
    raw = '대상: ["Emma", "emma", "dentist", "", "' + "x" * 80 + '", "a", "b", "c"]'
    assert parse_entities(raw) == ["Emma", "dentist", "a", "b"][:MAX_ENTITIES]


@pytest.mark.parametrize("raw", ["없음", "[broken", '{"a": 1}', "[1, 2]"])
def test_parse_entities_bad_reply_is_empty(raw):
    assert parse_entities(raw) == []


async def test_llm_extractor_reads_reply_and_returns_empty_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = [
        AssistantMessage(content=[TextContent(text='["Emma"]')], provider="openai", model="m"),
        AssistantMessage(content=[], provider="openai", model="m", error_message="timeout"),
    ]

    async def fake(model, ctx, opts):  # type: ignore[no-untyped-def]
        return replies.pop(0)

    monkeypatch.setattr(stream_mod, "stream_to_message", fake)
    extract = llm_entity_extractor(MODEL)

    assert await extract("Emma 랑 어디 갔더라?") == ["Emma"]
    assert await extract("Emma 랑 어디 갔더라?") == []
