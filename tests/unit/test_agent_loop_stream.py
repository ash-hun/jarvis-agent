"""agent_loop: stream 의 프로바이더 선택과 stream_to_message 가 글, 도구 호출, 오류를 메시지로 모으는지 검증한다."""

import pytest

from jarvis.model_layer.model_types import (
    ErrorEvent,
    LLMContext,
    ModelConfig,
    StopEvent,
    TextDeltaEvent,
    UserMessage,
)
from tests.fixtures.agent_loop_helpers import ScriptedProvider, register
from jarvis.model_layer.stream import stream, stream_to_message

SIMPLE = LLMContext(messages=[UserMessage(content="Say hello")])


async def test_stream_yields_text_deltas_then_one_stop(faux_model_with_response):
    model = faux_model_with_response("Hello World")

    events = [event async for event in stream(model, SIMPLE)]

    assert [e for e in events if isinstance(e, TextDeltaEvent)]
    stop_events = [e for e in events if isinstance(e, StopEvent)]
    assert len(stop_events) == 1 and stop_events[0].reason == "stop"


@pytest.mark.parametrize(
    ("response", "ctx"),
    [
        ("Hello from Jarvis!", SIMPLE),
        ("I am your assistant", LLMContext(messages=[UserMessage(content="Who are you?")],
                                           system_prompt="You are Jarvis, a personal assistant.")),
        ("", SIMPLE),
    ],
    ids=["text", "with_system_prompt", "empty"],
)
async def test_stream_to_message_collects_text(faux_model_with_response, response, ctx):
    model = faux_model_with_response(response)

    msg = await stream_to_message(model, ctx)

    assert msg.text().strip() == response
    assert msg.tool_calls() == []
    assert (msg.provider, msg.stop_reason, msg.usage.input, msg.usage.output) == ("faux", "stop", 10, 5)


async def test_stream_to_message_collects_tool_call(faux_model_with_response):
    model = faux_model_with_response(
        response="", tool_calls=[{"id": "tc_001", "name": "bash", "arguments": {"command": "ls"}}]
    )

    msg = await stream_to_message(model, SIMPLE)

    assert [(tc.id, tc.name, tc.arguments) for tc in msg.tool_calls()] == [("tc_001", "bash", {"command": "ls"})]
    assert msg.stop_reason == "tool_use"


async def test_unknown_provider_raises():
    bad_model = ModelConfig(provider="nonexistent", model="x")

    with pytest.raises(KeyError, match="nonexistent"):
        async for _ in stream(bad_model, SIMPLE):
            pass


async def test_stream_to_message_surfaces_provider_error():
    """ErrorEvent 가 오면 error_message 에 담긴다. 호출자가 빈 응답과 실패를 구분할 수 있어야 한다."""
    model = register(ScriptedProvider([[ErrorEvent(message="Faux error for testing", code="test_error")]]))

    msg = await stream_to_message(model, SIMPLE)

    assert msg.error_message == "Faux error for testing"
    assert msg.text() == ""
