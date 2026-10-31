"""usermodel: builder 가 기억을 사용자 모델로 증류하고 소스가 없거나 답이 깨지면 이전 모델을 지키는지 검증."""

import json
import pytest

from jarvis.agent_layer.usermodel import UserModel, UserModelBuilder

MODEL_JSON = json.dumps({"summary": "간결·직접적 답 선호", "traits": ["Python", "테스트 우선"]}, ensure_ascii=False)


async def test_build_distills_model(faux_model_with_response):
    builder = UserModelBuilder(model=faux_model_with_response(response=MODEL_JSON))

    result = await builder.build(["세션 요약 1", "세션 요약 2"])

    assert result is not None
    assert result.summary == "간결·직접적 답 선호"
    assert "Python" in result.traits
    assert result.source_count == 2


@pytest.mark.parametrize(
    ("response", "sources"),
    [(MODEL_JSON, []), ("JSON 아님", ["소스"])],
    ids=["empty_sources", "broken_json"],
)
async def test_build_keeps_previous_model(faux_model_with_response, response, sources):
    builder = UserModelBuilder(model=faux_model_with_response(response=response))
    prev = UserModel(summary="이전")

    assert await builder.build(sources, previous=prev) is prev
