"""thought 테스트가 함께 쓰는 가짜 LLM 경계: 모듈의 stream_to_message 를 고정 답으로 바꾸고 받은 호출을 남긴다."""

import pytest
import asyncio
from types import ModuleType
from dataclasses import dataclass, field

from jarvis.model_layer.model_types import AssistantMessage, ModelConfig, TextContent


@dataclass
class LLMCalls:
    prompts: list[str] = field(default_factory=list)
    models: list[ModelConfig] = field(default_factory=list)


def fake_llm(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    reply: str = "",
    delay: float = 0.0,
    error: Exception | None = None,
) -> LLMCalls:
    """module.stream_to_message 를 reply 를 돌려주는 가짜로 바꾼다. error 면 그 예외를 던진다."""
    calls = LLMCalls()

    async def fake_stream(model, ctx, options):  # type: ignore[no-untyped-def]
        calls.models.append(model)
        calls.prompts.append(ctx.messages[0].content)
        if delay:
            await asyncio.sleep(delay)
        if error is not None:
            raise error
        return AssistantMessage(content=[TextContent(text=reply)] if reply else [])

    monkeypatch.setattr(module, "stream_to_message", fake_stream)
    return calls
