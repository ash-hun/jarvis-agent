"""[model_layer] Gemini 스트림은 generate_content_stream 코루틴을 await 한 결과를 순회한다."""

import types
import pytest

from jarvis.model_layer.types import LLMContext, ModelConfig, StopEvent, TextDeltaEvent, UserMessage


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


@pytest.mark.asyncio
async def test_stream_awaits_coroutine_and_yields_text(monkeypatch):
    pytest.importorskip("google.genai")
    from google import genai

    from jarvis.model_layer.providers.gemini import GeminiProvider

    async def generate_content_stream(**_kwargs):
        # 실제 SDK 처럼 await 해야 스트림이 나오는 코루틴
        return _stream_of([_Chunk("안녕"), _Chunk("하세요", finish="STOP")])

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            models = types.SimpleNamespace(generate_content_stream=generate_content_stream)
            self.aio = types.SimpleNamespace(models=models)

    monkeypatch.setattr(genai, "Client", FakeClient)
    events = [
        e
        async for e in GeminiProvider().stream(
            ModelConfig(provider="gemini", model="gemini-test", api_key="k"),
            LLMContext(messages=[UserMessage(content="hi", timestamp=0)], tools=None),
        )
    ]
    assert [e.delta for e in events if isinstance(e, TextDeltaEvent)] == ["안녕", "하세요"]
    assert isinstance(events[-1], StopEvent)
