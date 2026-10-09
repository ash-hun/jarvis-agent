"""GeminiProvider 메시지 변환 및 기본 동작 테스트 (실 API 미사용)."""
from __future__ import annotations

from jarvis.model_layer.providers.gemini import _convert_messages
from jarvis.model_layer.types import (
    AssistantMessage,
    ImageContent,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

# ── LLMContext 헬퍼 ──────────────────────────────────────────────────────────

def _ctx(messages, system_prompt=None, tools=None):
    from jarvis.model_layer.types import LLMContext
    return LLMContext(messages=messages, system_prompt=system_prompt, tools=tools)


class TestConvertMessages:
    def test_user_text_message(self):
        ctx = _ctx([UserMessage(content="Hello Gemini")])
        result = _convert_messages(ctx)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["parts"] == [{"text": "Hello Gemini"}]

    def test_user_content_list(self):
        ctx = _ctx([UserMessage(content=[
            TextContent(text="Describe this"),
            ImageContent(data="abc123", mime_type="image/png"),
        ])])
        result = _convert_messages(ctx)
        parts = result[0]["parts"]
        assert parts[0] == {"text": "Describe this"}
        assert parts[1]["inline_data"]["mime_type"] == "image/png"
        assert parts[1]["inline_data"]["data"] == "abc123"

    def test_assistant_text_message(self):
        ctx = _ctx([AssistantMessage(content=[TextContent(text="I can help!")])])
        result = _convert_messages(ctx)
        assert len(result) == 1
        assert result[0]["role"] == "model"
        assert result[0]["parts"] == [{"text": "I can help!"}]

    def test_assistant_with_tool_call(self):
        ctx = _ctx([AssistantMessage(content=[
            TextContent(text="Let me search"),
            ToolCall(id="call_1", name="web_search", arguments={"query": "python"}),
        ])])
        result = _convert_messages(ctx)
        assert result[0]["role"] == "model"
        parts = result[0]["parts"]
        assert parts[0] == {"text": "Let me search"}
        assert parts[1]["function_call"]["name"] == "web_search"
        assert parts[1]["function_call"]["args"] == {"query": "python"}

    def test_tool_result_message(self):
        ctx = _ctx([ToolResultMessage(
            tool_call_id="call_1",
            tool_name="web_search",
            content=[TextContent(text="Found 5 results")],
            is_error=False,
        )])
        result = _convert_messages(ctx)
        assert result[0]["role"] == "user"
        part = result[0]["parts"][0]
        assert part["function_response"]["name"] == "web_search"
        assert part["function_response"]["response"]["result"] == "Found 5 results"

    def test_tool_result_error_includes_error_field(self):
        ctx = _ctx([ToolResultMessage(
            tool_call_id="call_1",
            tool_name="bash",
            content=[TextContent(text="Command not found")],
            is_error=True,
        )])
        result = _convert_messages(ctx)
        response = result[0]["parts"][0]["function_response"]["response"]
        assert "error" in response
        assert response["error"] == "Command not found"

    def test_assistant_thinking_block_excluded(self):
        """ThinkingContent 블록은 Gemini로 변환 시 포함되지 않아야 함."""
        ctx = _ctx([AssistantMessage(content=[
            ThinkingContent(thinking="Let me think..."),
            TextContent(text="Here is my answer"),
        ])])
        result = _convert_messages(ctx)
        # thinking 블록은 type="thinking"이므로 parts에 포함 안 됨
        assert result[0]["parts"] == [{"text": "Here is my answer"}]

    def test_multi_turn_conversation(self):
        ctx = _ctx([
            UserMessage(content="What is Python?"),
            AssistantMessage(content=[TextContent(text="Python is a language")]),
            UserMessage(content="Tell me more"),
        ])
        result = _convert_messages(ctx)
        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "model"
        assert result[2]["role"] == "user"

    def test_empty_assistant_content_excluded(self):
        """빈 parts의 assistant 메시지는 결과에서 제외."""
        ctx = _ctx([AssistantMessage(content=[])])
        result = _convert_messages(ctx)
        assert len(result) == 0


class TestGeminiProviderMetadata:
    def test_provider_name(self):
        from jarvis.model_layer.providers.gemini import GeminiProvider
        p = GeminiProvider()
        assert p.provider_name == "gemini"

    def test_supports_thinking_false(self):
        from jarvis.model_layer.providers.gemini import GeminiProvider
        assert GeminiProvider().supports_thinking() is False

    def test_supports_images_true(self):
        from jarvis.model_layer.providers.gemini import GeminiProvider
        assert GeminiProvider().supports_images() is True

    async def test_stream_yields_error_when_package_missing(self):
        """google-genai 미설치 시 ErrorEvent 반환."""
        import sys
        from unittest.mock import patch

        from jarvis.model_layer.providers.gemini import GeminiProvider
        from jarvis.model_layer.types import ErrorEvent, LLMContext, ModelConfig

        provider = GeminiProvider()
        model = ModelConfig(provider="gemini", model="gemini-2.0-flash", api_key="test")
        ctx = LLMContext(messages=[], system_prompt=None)

        with patch.dict(sys.modules, {"google": None, "google.genai": None}):
            events = []
            async for ev in provider.stream(model, ctx):
                events.append(ev)

        assert any(isinstance(ev, ErrorEvent) for ev in events)
        error_ev = next(ev for ev in events if isinstance(ev, ErrorEvent))
        assert "google-genai" in error_ev.message


class TestGeminiInRegistry:
    def test_gemini_registered_in_default_registry(self):
        from jarvis.model_layer.registry import build_default_registry
        registry = build_default_registry()
        assert "gemini" in registry.list_names()
