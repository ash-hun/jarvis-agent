"""[model_layer] 모든 LLM 프로바이더가 상속하는 기본 프로바이더 클래스를 정의한다."""

from __future__ import annotations

from collections.abc import AsyncIterator

from jarvis.model_layer.types import ErrorEvent, LLMContext, ModelConfig, StreamEvent, StreamOptions

NOT_IMPLEMENTED_CODE = "not_implemented"


class Provider:
    """LLM 프로바이더의 기본 클래스. 하위 클래스는 provider_name 과 stream() 을 채운다."""

    provider_name: str = ""

    async def stream(
        self,
        model: ModelConfig,
        context: LLMContext,
        options: StreamOptions | None = None,
    ) -> AsyncIterator[StreamEvent]:
        # 예외 대신 ErrorEvent 로 알린다. 호출자는 프로바이더 오류를 이벤트로만 받는다
        message = f"provider {self.provider_name!r} does not implement stream"
        yield ErrorEvent(message=message, code=NOT_IMPLEMENTED_CODE)

    def supports_thinking(self) -> bool:
        return False

    def supports_images(self) -> bool:
        return False
