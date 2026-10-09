from __future__ import annotations

import json
from collections.abc import AsyncIterator

from jarvis.model_layer.types import (
    LLMContext,
    ModelConfig,
    StopEvent,
    StreamEvent,
    StreamOptions,
    TextDeltaEvent,
    ToolCallDeltaEvent,
    Usage,
)


class FauxProvider:
    """
    실 LLM API 호출 없는 테스트용 프로바이더.
    Pi: faux provider 패턴 동일.
    """

    provider_name = "faux"

    def __init__(
        self,
        response: str = "Hello from Jarvis!",
        tool_calls: list[dict] | None = None,
        usage: Usage | None = None,
    ) -> None:
        self._response = response
        self._tool_calls = tool_calls or []
        self._usage = usage or Usage(input=10, output=5)

    def supports_thinking(self) -> bool:
        return False

    def supports_images(self) -> bool:
        return False

    async def stream(
        self,
        model: ModelConfig,
        context: LLMContext,
        options: StreamOptions | None = None,
    ) -> AsyncIterator[StreamEvent]:
        if self._response:
            for word in self._response.split():
                yield TextDeltaEvent(delta=word + " ")

        for tc in self._tool_calls:
            yield ToolCallDeltaEvent(
                id=tc["id"],
                name=tc["name"],
                arguments_delta=json.dumps(tc.get("arguments", {})),
            )

        stop_reason = "tool_use" if self._tool_calls else "stop"
        yield StopEvent(reason=stop_reason, usage=self._usage)  # type: ignore[arg-type]


class FauxProviderFactory:
    """시나리오별 FauxProvider를 빠르게 생성."""

    @staticmethod
    def text(response: str = "Hello!") -> FauxProvider:
        return FauxProvider(response=response)

    @staticmethod
    def tool_call(name: str, arguments: dict, tc_id: str = "call_001") -> FauxProvider:
        return FauxProvider(
            response="",
            tool_calls=[{"id": tc_id, "name": name, "arguments": arguments}],
        )

    @staticmethod
    def error() -> FauxProvider:
        from jarvis.model_layer.types import ErrorEvent

        class _ErrorProvider(FauxProvider):
            async def stream(self, model, context, options=None):
                yield ErrorEvent(message="Faux error for testing", code="test_error")

        return _ErrorProvider()  # type: ignore[return-value]
