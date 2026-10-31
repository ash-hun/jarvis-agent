"""Ollama 프로바이더: 도구 호출이 있으면 stop 사유가 tool_use 여야 한다. 이력 재전송은 함수 이름을 보낸다."""

import json
import httpx
import pytest

from jarvis.model_layer.model_types import (
    AssistantMessage,
    LLMContext,
    ModelConfig,
    StopEvent,
    StreamOptions,
    TextContent,
    ThinkingDeltaEvent,
    Tool,
    ToolCall,
    ToolCallDeltaEvent,
    ToolResultMessage,
    UserMessage,
)
from jarvis.model_layer.providers.ollama import OllamaProvider, _convert_messages, _stop_reason
from jarvis.model_layer.providers import ollama as ollama_mod


@pytest.mark.parametrize(
    ("chunk", "had_tools", "reason"),
    [
        ({"done": True, "done_reason": "stop"}, False, "stop"),
        ({"done": True, "done_reason": "stop"}, True, "tool_use"),
        ({"done": True, "done_reason": "length"}, False, "length"),
        ({"done": True}, False, "stop"),
    ],
)
def test_stop_reason(chunk, had_tools, reason):
    assert _stop_reason(chunk, had_tools) == reason


def test_convert_messages_sends_function_name_not_call_id():
    ctx = LLMContext(
        messages=[
            UserMessage(content="hi"),
            AssistantMessage(content=[ToolCall(id="call_1", name="bash", arguments={"command": "ls"})]),
            ToolResultMessage(tool_call_id="call_1", tool_name="bash", content=[TextContent(text="ok")]),
        ]
    )
    converted = _convert_messages(ctx)
    assert converted[1]["tool_calls"] == [{"function": {"name": "bash", "arguments": {"command": "ls"}}}]
    assert converted[2] == {"role": "tool", "content": "ok"}


def _ndjson(*chunks: dict) -> bytes:
    return "".join(json.dumps(c) + "\n" for c in chunks).encode()


async def _stream_with(monkeypatch, body: bytes, options: StreamOptions | None = None, sent: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if sent is not None:
            sent.append(json.loads(request.content))
        return httpx.Response(200, content=body, headers={"content-type": "application/x-ndjson"})

    real = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(ollama_mod.httpx, "AsyncClient", fake_client)
    model = ModelConfig(provider="ollama", model="m", base_url="http://ollama.test")
    tool = Tool(name="bash", description="d", parameters={"type": "object", "properties": {}})
    ctx = LLMContext(messages=[UserMessage(content="run")], tools=[tool])
    return [ev async for ev in OllamaProvider().stream(model, ctx, options)]


async def test_stream_with_tool_call_ends_with_tool_use(monkeypatch):
    body = _ndjson(
        {"message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "bash", "arguments": {"command": "echo hi"}}}
        ]}, "done": False},
        {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop",
         "prompt_eval_count": 7, "eval_count": 3},
    )
    events = await _stream_with(monkeypatch, body)
    calls = [e for e in events if isinstance(e, ToolCallDeltaEvent)]
    stop = [e for e in events if isinstance(e, StopEvent)]
    assert calls and calls[0].name == "bash" and json.loads(calls[0].arguments_delta) == {"command": "echo hi"}
    assert stop and stop[0].reason == "tool_use" and stop[0].usage.input == 7


async def test_stream_text_only_ends_with_stop(monkeypatch):
    body = _ndjson(
        {"message": {"role": "assistant", "content": "안녕"}, "done": False},
        {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"},
    )
    events = await _stream_with(monkeypatch, body)
    assert [e for e in events if isinstance(e, StopEvent)][0].reason == "stop"


@pytest.mark.parametrize(("options", "think"), [(None, False), (StreamOptions(enable_thinking=True), True)])
async def test_thinking_is_off_unless_requested(monkeypatch, options, think):
    """생각하는 모델은 think 기본값이 on 이라 content 가 비어 온다. 요청하지 않으면 끈다."""
    body = _ndjson({"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"})
    sent: list[dict] = []
    await _stream_with(monkeypatch, body, options, sent)
    assert sent[0]["think"] is think


@pytest.mark.parametrize("schema", [None, {"type": "object", "properties": {"a": {"type": "string"}}}])
async def test_format_is_sent_only_with_schema(monkeypatch, schema):
    body = _ndjson({"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"})
    sent: list[dict] = []
    await _stream_with(monkeypatch, body, StreamOptions(json_schema=schema), sent)
    assert sent[0].get("format") == schema


async def test_thinking_is_off_unless_asked_and_streamed_when_on(monkeypatch):
    body = _ndjson(
        {"message": {"thinking": "먼저 목록을 보고"}},
        {"message": {"content": "다 봤어요"}},
        {"done": True, "done_reason": "stop"},
    )
    sent: list = []
    events = await _stream_with(monkeypatch, body, StreamOptions(enable_thinking=True), sent=sent)
    assert sent[0]["think"] is True
    assert [e.thinking for e in events if isinstance(e, ThinkingDeltaEvent)] == ["먼저 목록을 보고"]
    assert OllamaProvider().supports_thinking()

    await _stream_with(monkeypatch, _ndjson({"done": True}), sent=sent)
    assert sent[1]["think"] is False  # 기본은 끈다. 켜면 작은 모델이 출력 한도를 생각에 다 쓴다
