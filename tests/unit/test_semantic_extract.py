"""의미 추출: JSON 파싱의 관대함과 LLM 실패 시 빈 결과."""

from jarvis.memory.consolidation.semantic_extract import Fact, llm_fact_extractor, parse_facts
from jarvis.memory.long_term.semantic import fact_key


def test_parse_facts_accepts_surrounding_prose_and_clamps_importance():
    raw = '설명입니다. [{"key": "거주지", "value": "부산", "importance": 1.7}, {"key": "", "value": "x"}, "junk"] 끝.'
    assert parse_facts(raw) == [Fact("거주지", "부산", 1.0)]


def test_parse_facts_returns_empty_on_garbage():
    assert parse_facts("") == []
    assert parse_facts("not json") == []
    assert parse_facts('{"key": "a"}') == []
    assert parse_facts('[{"key": "a", "value": "b", "importance": "high"}]') == [Fact("a", "b", 0.5)]


def test_fact_content_is_key_colon_value_and_round_trips_through_fact_key():
    fact = Fact("주력 언어", "Python")
    assert fact.content == "주력 언어: Python"
    assert fact_key(fact.content) == "주력 언어"
    assert fact_key("콜론 없음") is None
    assert fact_key("x" * 50 + ": y") is None


async def test_llm_extractor_parses_model_output(faux_model_with_response):
    model = faux_model_with_response('[{"key": "거주지", "value": "부산", "importance": 0.8}]')
    facts = await llm_fact_extractor(model)("세션 요약")
    assert facts == [Fact("거주지", "부산", 0.8)]


async def test_llm_extractor_returns_empty_on_provider_error():
    from jarvis.model_layer.registry import get_default_registry
    from jarvis.model_layer.types import ModelConfig
    from tests.fixtures.faux_provider import FauxProviderFactory

    get_default_registry()._providers["faux"] = FauxProviderFactory.error()
    assert await llm_fact_extractor(ModelConfig(provider="faux", model="faux-model"))("요약") == []
