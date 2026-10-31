"""agent_loop: Anthropic 프로바이더가 직전 메시지의 마지막 블록에 캐시 지점을 넣어 보내는지 검증한다."""

import pytest
from typing import Any
from types import SimpleNamespace

from jarvis.model_layer.model_types import (
    AssistantMessage,
    LLMContext,
    Message,
    ModelConfig,
    TextContent,
    UserMessage,
)
from jarvis.model_layer.providers.anthropic import AnthropicProvider
from jarvis.model_layer.providers import anthropic as anthropic_mod

CACHE = {"type": "ephemeral"}


class _FakeStream:
    async def __aenter__(self) -> "_FakeStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> "_FakeStream":
        return self

    async def __anext__(self) -> Any:
        raise StopAsyncIteration

    async def get_final_message(self) -> Any:
        return SimpleNamespace(usage=SimpleNamespace(input_tokens=1, output_tokens=1), stop_reason="end_turn")


async def _sent_messages(monkeypatch: pytest.MonkeyPatch, messages: list[Message]) -> list[dict[str, Any]]:
    sent: dict[str, Any] = {}

    def stream(**kwargs: Any) -> _FakeStream:
        sent.update(kwargs)
        return _FakeStream()

    def fake_client(**_kwargs: Any) -> Any:
        return SimpleNamespace(messages=SimpleNamespace(stream=stream))

    monkeypatch.setattr(anthropic_mod.anthropic, "AsyncAnthropic", fake_client)
    model = ModelConfig(provider="anthropic", model="claude", api_key="k")
    [ev async for ev in AnthropicProvider().stream(model, LLMContext(messages=messages))]
    return sent["messages"]


def _text(text: str, cache: bool = False) -> dict[str, Any]:
    return {"type": "text", "text": text, **({"cache_control": CACHE} if cache else {})}


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        ([UserMessage(content="hello")], [{"role": "user", "content": "hello"}]),
        (
            [
                UserMessage(content=[TextContent(text="hi")]),
                AssistantMessage(content=[TextContent(text="hello")]),
                UserMessage(content=[TextContent(text="again")]),
            ],
            [
                {"role": "user", "content": [_text("hi")]},
                {"role": "assistant", "content": [_text("hello", cache=True)]},
                {"role": "user", "content": [_text("again")]},
            ],
        ),
        (
            [UserMessage(content="first"), UserMessage(content="second")],
            [{"role": "user", "content": [_text("first", cache=True)]}, {"role": "user", "content": "second"}],
        ),
        (
            [UserMessage(content=[]), UserMessage(content="current")],
            [{"role": "user", "content": []}, {"role": "user", "content": "current"}],
        ),
    ],
    ids=["single_message_untouched", "previous_turn_cached", "string_content_listed", "empty_content_untouched"],
)
async def test_stream_caches_history_up_to_previous_message(monkeypatch, messages, expected):
    assert await _sent_messages(monkeypatch, messages) == expected
