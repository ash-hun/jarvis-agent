"""memory 기능의 사실 추출: JSON 파싱의 관대함과 LLM 실패 시 빈 결과."""

import pytest

from jarvis.memory.consolidation.semantic_extract import Fact, llm_fact_extractor, parse_facts
from jarvis.model_layer.model_types import AssistantMessage


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            '설명입니다. [{"key": "거주지", "value": "부산", "importance": 1.7},'
            ' {"key": "", "value": "x"}, "junk"] 끝.',
            [Fact("거주지", "부산", 1.0)],
        ),
        ('[{"key": "a", "value": "b", "importance": "high"}]', [Fact("a", "b", 0.5)]),
        ("", []),
        ("not json", []),
        ('{"key": "a"}', []),
    ],
    ids=["prose_and_clamp", "bad_importance_defaults", "empty", "not_json", "not_a_list"],
)
def test_parse_facts_tolerates_prose_and_drops_garbage(raw, expected):
    assert parse_facts(raw) == expected


def test_fact_content_is_key_colon_value():
    assert Fact("주력 언어", "Python").content == "주력 언어: Python"


async def test_llm_extractor_parses_model_output(faux_model_with_response):
    model = faux_model_with_response('[{"key": "거주지", "value": "부산", "importance": 0.8}]')

    facts = await llm_fact_extractor(model)("세션 요약")

    assert facts == [Fact("거주지", "부산", 0.8)]


async def test_llm_extractor_returns_empty_on_provider_error(monkeypatch, faux_model):
    async def fake_stream(model, ctx, options):
        return AssistantMessage(content=[], error_message="provider down")

    monkeypatch.setattr("jarvis.model_layer.stream.stream_to_message", fake_stream)

    assert await llm_fact_extractor(faux_model)("요약") == []
