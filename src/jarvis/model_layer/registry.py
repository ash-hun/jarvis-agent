from __future__ import annotations

from jarvis.model_layer.providers.base import Provider


class ProviderRegistry:
    """
    프로바이더 등록/조회 레지스트리.
    first-registration-wins 정책.
    """

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        if provider.provider_name not in self._providers:
            self._providers[provider.provider_name] = provider

    def get(self, name: str) -> Provider:
        if name not in self._providers:
            raise KeyError(f"Provider '{name}' not registered. Available: {list(self._providers)}")
        return self._providers[name]

    def list_names(self) -> list[str]:
        return list(self._providers.keys())


def build_default_registry() -> ProviderRegistry:
    from jarvis.model_layer.providers.anthropic import AnthropicProvider
    from jarvis.model_layer.providers.gemini import GeminiProvider
    from jarvis.model_layer.providers.ollama import OllamaProvider
    from jarvis.model_layer.providers.openai import OpenAIProvider
    from jarvis.model_layer.providers.vllm import VLLMProvider

    registry = ProviderRegistry()
    registry.register(AnthropicProvider())
    registry.register(OpenAIProvider())
    registry.register(OllamaProvider())
    registry.register(VLLMProvider())
    registry.register(GeminiProvider())
    return registry


_default_registry: ProviderRegistry | None = None


def get_default_registry() -> ProviderRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = build_default_registry()
    return _default_registry
