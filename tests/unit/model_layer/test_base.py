"""Provider/Embedder 기본 클래스: 기본 동작과 기본 제공 구현의 상속 관계를 확인한다."""

import pytest

from jarvis.model_layer.model_types import ErrorEvent, LLMContext, ModelConfig, StreamEvent, UserMessage
from jarvis.model_layer.embeddings import Embedder, OllamaEmbedder, OpenAIEmbedder, VLLMEmbedder
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


def test_base_capabilities_default_to_false() -> None:
    assert Provider().supports_thinking() is False
    assert Provider().supports_images() is False


@pytest.mark.parametrize(
    ("cls", "name", "thinking", "images"),
    [
        (AnthropicProvider, "anthropic", True, True),
        (OpenAIProvider, "openai", False, True),
        (OllamaProvider, "ollama", True, True),
        (VLLMProvider, "vllm", False, False),
        (GeminiProvider, "gemini", False, True),
    ],
)
def test_builtin_providers_inherit_base_and_keep_capabilities(
    cls: type[Provider], name: str, thinking: bool, images: bool
) -> None:
    provider = cls()
    assert isinstance(provider, Provider)
    assert provider.provider_name == name
    assert provider.supports_thinking() is thinking
    assert provider.supports_images() is images


def test_builtin_embedders_inherit_base() -> None:
    assert isinstance(OpenAIEmbedder(api_key=None), Embedder)
    assert isinstance(OllamaEmbedder(), Embedder)
    assert isinstance(VLLMEmbedder(model="m", dimensions=4), Embedder)


async def test_base_embedder_requires_backend() -> None:
    with pytest.raises(NotImplementedError):
        await Embedder().embed(["a"])
