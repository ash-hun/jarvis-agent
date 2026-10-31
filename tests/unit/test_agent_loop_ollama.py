"""agent_loop: Ollama 프로바이더의 NDJSON 해석, 멈춤 사유, 요청 모양(이력, think, format)을 검증한다."""

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
from jarvis.model_layer.providers.ollama import OllamaProvider
from jarvis.model_layer.providers import ollama as ollama_mod

TOOL = Tool(name="bash", description="d", parameters={"type": "object", "properties": {}})
DONE = {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"}
TOOL_CHUNK = {"message": {"role": "assistant", "content": "", "tool_calls": [
    {"function": {"name": "bash", "arguments": {"command": "echo hi"}}}
]}, "done": False}


def _ndjson(*chunks: dict) -> bytes:
    return "".join(json.dumps(c) + "\n" for c in chunks).encode()


async def _stream_with(monkeypatch, body: bytes, options: StreamOptions | None = None, sent: list | None = None,
                       ctx: LLMContext | None = None):
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
    ctx = ctx or LLMContext(messages=[UserMessage(content="run")], tools=[TOOL])
    return [ev async for ev in OllamaProvider().stream(model, ctx, options)]


async def test_stream_with_tool_call_ends_with_tool_use(monkeypatch):
    body = _ndjson(TOOL_CHUNK, {**DONE, "prompt_eval_count": 7, "eval_count": 3})

    events = await _stream_with(monkeypatch, body)

    calls = [e for e in events if isinstance(e, ToolCallDeltaEvent)]
    stop = [e for e in events if isinstance(e, StopEvent)]
    assert calls and calls[0].name == "bash" and json.loads(calls[0].arguments_delta) == {"command": "echo hi"}
    assert stop and stop[0].reason == "tool_use" and stop[0].usage.input == 7


@pytest.mark.parametrize(
    ("chunks", "reason"),
    [
        ([{"message": {"role": "assistant", "content": "안녕"}, "done": False}, DONE], "stop"),
        ([TOOL_CHUNK, DONE], "tool_use"),
        ([{"done": True, "done_reason": "length"}], "length"),
        ([{"done": True}], "stop"),
    ],
    ids=["text_stop", "tools_override_stop", "length", "missing_reason"],
)
async def test_stream_stop_reason(monkeypatch, chunks, reason):
    events = await _stream_with(monkeypatch, _ndjson(*chunks))

    assert [e.reason for e in events if isinstance(e, StopEvent)] == [reason]


async def test_history_sends_function_name_not_call_id(monkeypatch):
    ctx = LLMContext(
        messages=[
            UserMessage(content="hi"),
            AssistantMessage(content=[ToolCall(id="call_1", name="bash", arguments={"command": "ls"})]),
            ToolResultMessage(tool_call_id="call_1", tool_name="bash", content=[TextContent(text="ok")]),
        ]
    )
    sent: list[dict] = []

    await _stream_with(monkeypatch, _ndjson(DONE), sent=sent, ctx=ctx)

    messages = sent[0]["messages"]
    assert messages[1]["tool_calls"] == [{"function": {"name": "bash", "arguments": {"command": "ls"}}}]
    assert messages[2] == {"role": "tool", "content": "ok"}


@pytest.mark.parametrize(("options", "think"), [(None, False), (StreamOptions(enable_thinking=True), True)])
async def test_thinking_is_off_unless_requested(monkeypatch, options, think):
    """생각하는 모델은 think 기본값이 on 이라 content 가 비어 온다. 켜면 작은 모델이 출력 한도를 생각에 다 쓴다."""
    sent: list[dict] = []

    await _stream_with(monkeypatch, _ndjson(DONE), options, sent)

    assert sent[0]["think"] is think


async def test_thinking_is_streamed_as_thinking_deltas_when_on(monkeypatch):
    body = _ndjson({"message": {"thinking": "먼저 목록을 보고"}}, {"message": {"content": "다 봤어요"}}, {"done": True})

    events = await _stream_with(monkeypatch, body, StreamOptions(enable_thinking=True))

    assert [e.thinking for e in events if isinstance(e, ThinkingDeltaEvent)] == ["먼저 목록을 보고"]


@pytest.mark.parametrize("schema", [None, {"type": "object", "properties": {"a": {"type": "string"}}}])
async def test_format_is_sent_only_with_schema(monkeypatch, schema):
    sent: list[dict] = []

    await _stream_with(monkeypatch, _ndjson(DONE), StreamOptions(json_schema=schema), sent)

    assert sent[0].get("format") == schema


async def test_same_tool_twice_without_ids_gets_distinct_call_ids(monkeypatch):
    twice = {"message": {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "bash", "arguments": {"command": "ls"}}},
        {"function": {"name": "bash", "arguments": {"command": "pwd"}}},
    ]}, "done": False}

    events = await _stream_with(monkeypatch, _ndjson(twice, DONE))

    calls = [e for e in events if isinstance(e, ToolCallDeltaEvent)]
    assert len({c.id for c in calls}) == 2
    assert [json.loads(c.arguments_delta) for c in calls] == [{"command": "ls"}, {"command": "pwd"}]
