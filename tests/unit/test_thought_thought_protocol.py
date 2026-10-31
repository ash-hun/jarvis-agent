"""thought 의 ThoughtEngine 기본 클래스: 기본 엔진은 사고하지 않는지 검증한다."""

from jarvis.agent_layer.thought import ThoughtEngine, ThoughtRequest


async def test_thought_engine_base_is_disabled():
    assert await ThoughtEngine().think(ThoughtRequest(user_input="안녕")) is None
