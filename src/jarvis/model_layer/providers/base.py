from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from jarvis.model_layer.types import LLMContext, ModelConfig, StreamEvent, StreamOptions


@runtime_checkable
class Provider(Protocol):
    """모든 LLM 프로바이더가 구현해야 하는 Protocol."""

    provider_name: str

    async def stream(
        self,
        model: ModelConfig,
        context: LLMContext,
        options: StreamOptions | None = None,
    ) -> AsyncIterator[StreamEvent]: ...

    def supports_thinking(self) -> bool: ...

    def supports_images(self) -> bool: ...
