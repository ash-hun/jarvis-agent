"""agent_loop: Gemini 프로바이더의 메시지 변환, 코루틴 스트림 순회, SDK 미설치 오류를 가짜 클라이언트로 검증한다."""

import sys
import types
import pytest
from typing import Any
from unittest.mock import patch

from jarvis.model_layer.model_types import (
    AssistantMessage,
    ErrorEvent,
    ImageContent,
    LLMContext,
    Message,
    ModelConfig,
    StopEvent,
    StreamEvent,
    TextContent,
    TextDeltaEvent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from jarvis.model_layer.providers.gemini import GeminiProvider

IMAGE = ImageContent(data="abc123", mime_type="image/png")
MODEL = ModelConfig(provider="gemini", model="gemini-test", api_key="k")


class _Chunk:
    def __init__(self, text: str, finish: str | None = None) -> None:
        part = types.SimpleNamespace(text=text, function_call=None)
        content = types.SimpleNamespace(parts=[part])
        reason = types.SimpleNamespace(name=finish) if finish else None
        self.candidates = [types.SimpleNamespace(content=content, finish_reason=reason)]
        self.usage_metadata = None


async def _stream_of(chunks: list[_Chunk]):
    for c in chunks:
        yield c


async def _run(monkeypatch, messages: list[Message], chunks: list[_Chunk]) -> tuple[list[StreamEvent], dict[str, Any]]:
    from google import genai

    sent: dict[str, Any] = {}

    async def generate_content_stream(**kwargs):
        sent.update(kwargs)
        # 실제 SDK 처럼 await 해야 스트림이 나오는 코루틴
        return _stream_of(chunks)

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            models = types.SimpleNamespace(generate_content_stream=generate_content_stream)
            self.aio = types.SimpleNamespace(models=models)

    monkeypatch.setattr(genai, "Client", FakeClient)
    events = [e async for e in GeminiProvider().stream(MODEL, LLMContext(messages=messages, tools=None))]
    return events, sent


async def test_stream_awaits_coroutine_and_yields_text(monkeypatch):
    pytest.importorskip("google.genai")

    chunks = [_Chunk("안녕"), _Chunk("하세요", "STOP")]

    events, _ = await _run(monkeypatch, [UserMessage(content="hi", timestamp=0)], chunks)

    assert [e.delta for e in events if isinstance(e, TextDeltaEvent)] == ["안녕", "하세요"]
    assert isinstance(events[-1], StopEvent)


def _result(text: str, is_error: bool) -> ToolResultMessage:
    return ToolResultMessage(tool_call_id="call_1", tool_name="web_search", content=[TextContent(text=text)],
                             is_error=is_error)


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        ([UserMessage(content="Hello Gemini")], [{"role": "user", "parts": [{"text": "Hello Gemini"}]}]),
        (
            [UserMessage(content=[TextContent(text="Describe this"), IMAGE])],
            [{"role": "user", "parts": [
                {"text": "Describe this"}, {"inline_data": {"mime_type": "image/png", "data": "abc123"}},
            ]}],
        ),
        (
            [AssistantMessage(content=[TextContent(text="I can help!")])],
            [{"role": "model", "parts": [{"text": "I can help!"}]}],
        ),
        (
            [AssistantMessage(content=[
                TextContent(text="Let me search"),
                ToolCall(id="call_1", name="web_search", arguments={"query": "python"}),
            ])],
            [{"role": "model", "parts": [
                {"text": "Let me search"}, {"function_call": {"name": "web_search", "args": {"query": "python"}}},
            ]}],
        ),
        (
            [_result("Found 5 results", False)],
            [{"role": "user", "parts": [
                {"function_response": {"name": "web_search", "response": {"result": "Found 5 results"}}},
            ]}],
        ),
        (
            [_result("Command not found", True)],
            [{"role": "user", "parts": [{"function_response": {
                "name": "web_search", "response": {"result": "Command not found", "error": "Command not found"},
            }}]}],
        ),
        (
            [AssistantMessage(content=[ThinkingContent(thinking="음..."), TextContent(text="Here is my answer")])],
            [{"role": "model", "parts": [{"text": "Here is my answer"}]}],
        ),
        (
            [
                UserMessage(content="What is Python?"),
                AssistantMessage(content=[TextContent(text="Python is a language")]),
                UserMessage(content="Tell me more"),
            ],
            [
                {"role": "user", "parts": [{"text": "What is Python?"}]},
                {"role": "model", "parts": [{"text": "Python is a language"}]},
                {"role": "user", "parts": [{"text": "Tell me more"}]},
            ],
        ),
        ([AssistantMessage(content=[])], []),
    ],
    ids=["user_text", "user_image", "assistant_text", "assistant_tool_call", "tool_result", "tool_error",
         "thinking_dropped", "multi_turn_roles", "empty_assistant_dropped"],
)
async def test_stream_sends_converted_contents(monkeypatch, messages, expected):
    pytest.importorskip("google.genai")

    _, sent = await _run(monkeypatch, messages, [])

    assert sent["contents"] == expected


async def test_stream_yields_error_when_package_missing():
    ctx = LLMContext(messages=[], system_prompt=None)

    with patch.dict(sys.modules, {"google": None, "google.genai": None}):
        events = [ev async for ev in GeminiProvider().stream(MODEL, ctx)]

    error = next(ev for ev in events if isinstance(ev, ErrorEvent))
    assert "google-genai" in error.message
