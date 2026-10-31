"""agent_loop: 기본 프로바이더 레지스트리에 기본 제공 프로바이더가 모두 등록되는지 검증한다."""

from jarvis.model_layer.model_registry import build_default_registry


def test_default_registry_lists_builtin_providers():
    names = build_default_registry().list_names()

    assert {"anthropic", "openai", "ollama", "vllm", "gemini"} <= set(names)
