"""OpenAI 프로바이더: 메시지 변환과 청크 스트림 해석을 가짜 SDK 클라이언트로 검증한다."""

import json
import pytest
from typing import Any
from types import SimpleNamespace

from jarvis.model_layer.model_types import (
    AssistantMessage,
    ImageContent,
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
from jarvis.model_layer.providers.openai import OpenAIProvider, _content_to_api, _convert_messages, _tool_to_openai
from jarvis.model_layer.providers import openai as openai_mod

TOOL = Tool(name="bash", description="d", parameters={"type": "object", "properties": {}})


def _chunk(content: str | None = None, tool_calls: list[Any] | None = None, finish: str | None = None) -> Any:
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)], usage=None)


def _tool_delta(index: int, id: str | None = None, name: str | None = None, args: str | None = None) -> Any:
    return SimpleNamespace(index=index, id=id, function=SimpleNamespace(name=name, arguments=args))


class _FakeStream:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    async def __aenter__(self) -> "_FakeStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> "_FakeStream":
        self._it = iter(self._chunks)
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, chunks: list[Any], sent: dict[str, Any]) -> None:
    async def create(**kwargs: Any) -> _FakeStream:
        sent.update(kwargs)
        return _FakeStream(chunks)

    def fake_client(**client_kwargs: Any) -> Any:
        sent["client"] = client_kwargs
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(openai_mod.openai_sdk, "AsyncOpenAI", fake_client)


async def test_stream_maps_text_tool_calls_usage_and_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    usage_chunk = SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=9, completion_tokens=4))
    chunks = [
        _chunk(content="hi"),
        _chunk(tool_calls=[_tool_delta(0, id="c1", name="bash", args='{"a"')]),
        _chunk(tool_calls=[_tool_delta(0, args=":1}")]),
        usage_chunk,
        _chunk(finish="tool_calls"),
    ]
    sent: dict[str, Any] = {}
    _install_fake_client(monkeypatch, chunks, sent)
    model = ModelConfig(provider="openai", model="gpt", api_key="k", base_url="http://x", timeout=5.0)
    ctx = LLMContext(messages=[UserMessage(content="run")], tools=[TOOL])
    events: list[StreamEvent] = [ev async for ev in OpenAIProvider().stream(model, ctx)]

    assert [e.delta for e in events if isinstance(e, TextDeltaEvent)] == ["hi"]
    calls = [e for e in events if isinstance(e, ToolCallDeltaEvent)]
    assert [(c.id, c.name, c.arguments_delta) for c in calls] == [("c1", "bash", '{"a"'), ("c1", "bash", ":1}")]
    stop = [e for e in events if isinstance(e, StopEvent)]
    assert stop[0].reason == "tool_use" and stop[0].usage.input == 9 and stop[0].usage.output == 4

    assert sent["client"] == {"api_key": "k", "base_url": "http://x", "timeout": 5.0}
    assert sent["stream"] is True and sent["stream_options"] == {"include_usage": True}
    assert sent["tools"] == [_tool_to_openai(TOOL)] and sent["tool_choice"] == "auto"


async def test_usage_after_finish_reaches_stop_event(monkeypatch: pytest.MonkeyPatch) -> None:
    # 실제 OpenAI 순서: finish_reason 조각 뒤에 choices 가 빈 사용량 조각이 온다
    usage_chunk = SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30))
    _install_fake_client(monkeypatch, [_chunk(content="hi"), _chunk(finish="stop"), usage_chunk], {})
    model = ModelConfig(provider="openai", model="gpt", api_key="k", timeout=5.0)
    events = [ev async for ev in OpenAIProvider().stream(model, LLMContext(messages=[UserMessage(content="hi")]))]

    stop = [e for e in events if isinstance(e, StopEvent)]
    assert len(stop) == 1
    assert (stop[0].reason, stop[0].usage.input, stop[0].usage.output) == ("stop", 120, 30)
    assert isinstance(events[-1], StopEvent)


async def test_stream_without_tools_omits_tool_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, Any] = {}
    _install_fake_client(monkeypatch, [_chunk(finish="weird")], sent)
    ctx = LLMContext(messages=[UserMessage(content="x")])
    events = [ev async for ev in OpenAIProvider().stream(ModelConfig(provider="openai", model="gpt"), ctx)]
    assert "tools" not in sent and "tool_choice" not in sent
    assert [e.reason for e in events if isinstance(e, StopEvent)] == ["stop"]


async def test_empty_base_url_falls_back_to_sdk_default(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, Any] = {}
    _install_fake_client(monkeypatch, [_chunk(finish="stop")], sent)
    ctx = LLMContext(messages=[UserMessage(content="x")])
    model = ModelConfig(provider="openai", model="gpt", base_url="")
    [ev async for ev in OpenAIProvider().stream(model, ctx)]
    assert sent["client"]["base_url"] is None


def test_convert_messages_roles_and_images() -> None:
    ctx = LLMContext(
        system_prompt="sys",
        messages=[
            UserMessage(content=[TextContent(text="see"), ImageContent(data="QUJD", mime_type="image/png")]),
            AssistantMessage(content=[TextContent(text="ok"), ToolCall(id="c1", name="bash", arguments={"x": 1})]),
            ToolResultMessage(tool_call_id="c1", tool_name="bash", content=[TextContent(text="done")]),
        ],
    )
    converted = _convert_messages(ctx)
    assert converted[0] == {"role": "system", "content": "sys"}
    assert converted[1]["content"] == [
        {"type": "text", "text": "see"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
    ]
    assert converted[2] == {
        "role": "assistant",
        "content": "ok",
        "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "bash", "arguments": json.dumps({"x": 1})}}
        ],
    }
    assert converted[3] == {"role": "tool", "tool_call_id": "c1", "content": "done"}


def test_assistant_without_text_has_no_content_key() -> None:
    ctx = LLMContext(messages=[AssistantMessage(content=[ToolCall(id="c1", name="bash", arguments={})])])
    assert "content" not in _convert_messages(ctx)[0]


def test_content_to_api_empty_list() -> None:
    assert _content_to_api([]) == []
