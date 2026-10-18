"""vLLM 프로바이더: OpenAI 호환 SSE 스트림 파싱과 요청 모양을 MockTransport 로 검증한다."""

import json
import httpx
import pytest
from typing import Any

from jarvis.model_layer.types import (
    AssistantMessage,
    ErrorEvent,
    LLMContext,
    ModelConfig,
    StopEvent,
    StreamEvent,
    TextContent,
    TextDeltaEvent,
    Tool,
    ToolCall,
    ToolCallDeltaEvent,
    ToolResultMessage,
    UserMessage,
)
from jarvis.model_layer.providers.vllm import VLLMProvider, _convert_messages, _tool_to_openai
from jarvis.model_layer.providers import vllm as vllm_mod

TOOL = Tool(name="bash", description="d", parameters={"type": "object", "properties": {}})


def _sse(*chunks: dict[str, Any]) -> bytes:
    lines = [f"data: {json.dumps(c)}" for c in chunks] + ["data: [DONE]"]
    return ("\n\n".join(lines) + "\n").encode()


async def _stream_with(
    monkeypatch: pytest.MonkeyPatch,
    handler: Any,  # httpx.MockTransport 핸들러. 테스트마다 응답 모양이 달라 시그니처를 고정하지 않는다
    model: ModelConfig | None = None,
) -> list[StreamEvent]:
    real = httpx.AsyncClient

    def fake_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(vllm_mod.httpx, "AsyncClient", fake_client)
    model = model or ModelConfig(provider="vllm", model="m", base_url="http://vllm.test/")
    ctx = LLMContext(messages=[UserMessage(content="run")], tools=[TOOL])
    return [ev async for ev in VLLMProvider().stream(model, ctx)]


async def test_stream_parses_text_tool_call_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[httpx.Request] = []
    body = _sse(
        {"choices": [{"delta": {"content": "안녕"}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "bash"}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\"a\":1}"}}]}}]},
        {
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    events = await _stream_with(monkeypatch, handler, ModelConfig(provider="vllm", model="m", api_key="k"))
    assert [e.delta for e in events if isinstance(e, TextDeltaEvent)] == ["안녕"]
    calls = [e for e in events if isinstance(e, ToolCallDeltaEvent)]
    assert len(calls) == 1 and calls[0].id == "c1" and calls[0].name == "bash" and calls[0].arguments_delta == '{"a":1}'
    stop = [e for e in events if isinstance(e, StopEvent)]
    assert stop[0].reason == "tool_use" and stop[0].usage.input == 5 and stop[0].usage.output == 2

    request = sent[0]
    assert str(request.url) == "http://localhost:8000/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer k"
    payload = json.loads(request.content)
    assert payload["stream"] is True and payload["tool_choice"] == "auto"
    assert payload["tools"] == [_tool_to_openai(TOOL)]


async def test_stream_strips_trailing_slash_and_omits_auth_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, content=_sse({"choices": [{"delta": {}, "finish_reason": "length"}]}))

    events = await _stream_with(monkeypatch, handler)
    assert str(sent[0].url) == "http://vllm.test/v1/chat/completions"
    assert "authorization" not in sent[0].headers
    assert [e.reason for e in events if isinstance(e, StopEvent)] == ["length"]


async def test_http_error_becomes_error_event(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"boom")

    events = await _stream_with(monkeypatch, handler)
    assert len(events) == 1 and isinstance(events[0], ErrorEvent)


def test_convert_messages_flattens_text_and_keeps_tool_ids() -> None:
    ctx = LLMContext(
        system_prompt="sys",
        messages=[
            UserMessage(content=[TextContent(text="a"), TextContent(text="b")]),
            AssistantMessage(content=[TextContent(text="ok"), ToolCall(id="c1", name="bash", arguments={"x": 1})]),
            ToolResultMessage(tool_call_id="c1", tool_name="bash", content=[TextContent(text="done")]),
        ],
    )
    converted = _convert_messages(ctx)
    assert converted[0] == {"role": "system", "content": "sys"}
    assert converted[1] == {"role": "user", "content": "a b"}
    assert converted[2]["content"] == "ok"
    assert converted[2]["tool_calls"] == [
        {"id": "c1", "type": "function", "function": {"name": "bash", "arguments": json.dumps({"x": 1})}}
    ]
    assert converted[3] == {"role": "tool", "tool_call_id": "c1", "content": "done"}
