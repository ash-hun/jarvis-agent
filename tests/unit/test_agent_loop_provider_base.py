"""agent_loop: 프로바이더 기본 클래스의 미구현 오류 이벤트와 기본 제공 프로바이더의 이름과 능력을 검증한다."""

import pytest

from jarvis.model_layer.model_types import ErrorEvent, LLMContext, ModelConfig, StreamEvent, UserMessage
from jarvis.model_layer.providers.provider_base import NOT_IMPLEMENTED_CODE, Provider
from jarvis.model_layer.providers.anthropic import AnthropicProvider
from jarvis.model_layer.providers.gemini import GeminiProvider
from jarvis.model_layer.providers.ollama import OllamaProvider
from jarvis.model_layer.providers.openai import OpenAIProvider
from jarvis.model_layer.providers.vllm import VLLMProvider


class _Bare(Provider):
    provider_name = "bare"


async def test_base_stream_yields_single_not_implemented_error() -> None:
    model = ModelConfig(provider="bare", model="m")
    ctx = LLMContext(messages=[UserMessage(content="hi")])

    events: list[StreamEvent] = [ev async for ev in _Bare().stream(model, ctx)]

    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert events[0].code == NOT_IMPLEMENTED_CODE and "bare" in events[0].message


@pytest.mark.parametrize(
    ("cls", "name", "thinking", "images"),
    [
        (Provider, "", False, False),
        (AnthropicProvider, "anthropic", True, True),
        (OpenAIProvider, "openai", False, True),
        (OllamaProvider, "ollama", True, True),
        (VLLMProvider, "vllm", False, False),
        (GeminiProvider, "gemini", False, True),
    ],
)
def test_providers_inherit_base_and_keep_capabilities(cls: type[Provider], name: str, thinking: bool, images: bool):
    provider = cls()

    assert isinstance(provider, Provider)
    assert provider.provider_name == name
    assert provider.supports_thinking() is thinking
    assert provider.supports_images() is images
