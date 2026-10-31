"""model_layer/stream.py: FauxProvider 기반 스트리밍 테스트."""
import pytest

from jarvis.model_layer.model_types import (
    LLMContext,
    ModelConfig,
    StopEvent,
    TextDeltaEvent,
    UserMessage,
)
from jarvis.model_layer.stream import stream, stream_to_message


@pytest.fixture
def faux_model():
    return ModelConfig(provider="faux", model="faux-model")


@pytest.fixture
def simple_context():
    return LLMContext(messages=[UserMessage(content="Say hello")])


async def test_stream_yields_text_deltas(faux_model, simple_context, faux_model_with_response):
    model = faux_model_with_response("Hello World")
    events = []
    async for event in stream(model, simple_context):
        events.append(event)

    text_events = [e for e in events if isinstance(e, TextDeltaEvent)]
    stop_events = [e for e in events if isinstance(e, StopEvent)]

    assert len(text_events) > 0
    assert len(stop_events) == 1
    assert stop_events[0].reason == "stop"


async def test_stream_to_message_text(faux_model_with_response, simple_context):
    model = faux_model_with_response("Hello from Jarvis!")
    msg = await stream_to_message(model, simple_context)

    assert "Hello" in msg.text()
    assert msg.provider == "faux"
    assert msg.stop_reason == "stop"
    assert msg.usage.input == 10
    assert msg.usage.output == 5


async def test_stream_to_message_tool_call(faux_model_with_response, simple_context):
    model = faux_model_with_response(
        response="",
        tool_calls=[{"id": "tc_001", "name": "bash", "arguments": {"command": "ls"}}],
    )
    msg = await stream_to_message(model, simple_context)

    assert len(msg.tool_calls()) == 1
    tc = msg.tool_calls()[0]
    assert tc.id == "tc_001"
    assert tc.name == "bash"
    assert tc.arguments == {"command": "ls"}
    assert msg.stop_reason == "tool_use"


async def test_stream_to_message_empty_response(faux_model_with_response, simple_context):
    model = faux_model_with_response("")
    msg = await stream_to_message(model, simple_context)
    assert msg.text() == ""
    assert len(msg.tool_calls()) == 0


async def test_stream_with_system_prompt(faux_model_with_response):
    model = faux_model_with_response("I am your assistant")
    ctx = LLMContext(
        messages=[UserMessage(content="Who are you?")],
        system_prompt="You are Jarvis, a personal assistant.",
    )
    msg = await stream_to_message(model, ctx)
    assert msg.text() != ""


async def test_unknown_provider_raises():
    bad_model = ModelConfig(provider="nonexistent", model="x")
    ctx = LLMContext(messages=[UserMessage(content="hi")])
    with pytest.raises(KeyError, match="nonexistent"):
        async for _ in stream(bad_model, ctx):
            pass


async def test_stream_to_message_surfaces_provider_error(faux_model, simple_context):
    """ErrorEvent 가 오면 error_message 에 담긴다. 호출자가 빈 응답과 실패를 구분할 수 있어야 한다."""
    from jarvis.model_layer.model_registry import get_default_registry
    from tests.fixtures.faux_provider import FauxProviderFactory

    get_default_registry()._providers["faux"] = FauxProviderFactory.error()
    msg = await stream_to_message(faux_model, simple_context)

    assert msg.error_message == "Faux error for testing"
    assert msg.text() == ""
