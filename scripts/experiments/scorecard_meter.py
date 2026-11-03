"""[scripts] 실제 provider 의 스트림 끝(StopEvent)에서 모델별 토큰 사용량을 모은다. 캐시로 답한 호출은 세지 않는다."""

from typing import Any
from contextlib import contextmanager
from collections.abc import AsyncIterator, Iterator
from scripts.experiments.scorecard_points import cost_usd

from jarvis.model_layer.model_types import LLMContext, ModelConfig, StopEvent, StreamEvent, StreamOptions
from jarvis.model_layer.providers.anthropic import AnthropicProvider
from jarvis.model_layer.providers.provider_base import Provider
from jarvis.model_layer.providers.ollama import OllamaProvider
from jarvis.model_layer.providers.openai import OpenAIProvider

# 감싸는 provider(실험의 호출 수 세기 등)는 이 클래스들의 인스턴스로 내려오므로 한 번만 센다
METERED = (AnthropicProvider, OpenAIProvider, OllamaProvider)


class BudgetExhausted(BaseException):
    """예산 provider 의 실제 비용이 상한에 닿았다. 실험의 넓은 except Exception 에 삼켜져 오답으로 캐시되지 않게
    BaseException 을 잇는다. 그 문항은 캐시되지 않고 프로세스가 멈춘다."""


class UsageMeter:
    """모델 이름마다 input, output, cache_read, cache_write, calls 를 더한다. 단가와 상한을 주면 호출 전에 멈춘다."""

    def __init__(self, prices: dict[str, dict[str, float]] | None = None, spent: float = 0.0,
                 cap: float | None = None) -> None:
        self.usage: dict[str, dict[str, int]] = {}
        self._prices = prices or {}
        self._spent = spent
        self._cap = cap

    def cost(self) -> float:
        """이 계량기가 센 예산 모델의 비용."""
        return sum(cost_usd(u, self._prices[m]) for m, u in self.usage.items() if m in self._prices)

    def check(self, model: str) -> None:
        if self._cap is not None and model in self._prices and self._spent + self.cost() >= self._cap:
            raise BudgetExhausted(f"예산 상한 ${self._cap:.2f} 도달(사용 ${self._spent + self.cost():.2f})")

    def add(self, model: str, event: StopEvent) -> None:
        row = self.usage.setdefault(model, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "calls": 0})
        row["input"] += event.usage.input
        row["output"] += event.usage.output
        row["cache_read"] += event.usage.cache_read
        row["cache_write"] += event.usage.cache_write
        row["calls"] += 1

    @contextmanager
    def installed(self) -> Iterator["UsageMeter"]:
        """provider 클래스의 stream 을 잠시 감싼다. 끝나면 원래대로 돌린다."""
        originals: dict[type[Provider], Any] = {cls: cls.stream for cls in METERED}
        meter = self

        def wrap(original: Any) -> Any:
            async def stream(
                self: Any, model: ModelConfig, context: LLMContext, options: StreamOptions | None = None
            ) -> AsyncIterator[StreamEvent]:
                meter.check(model.model)
                async for event in original(self, model, context, options):
                    if isinstance(event, StopEvent):
                        meter.add(model.model, event)
                    yield event

            return stream

        for cls, original in originals.items():
            cls.stream = wrap(original)  # type: ignore[method-assign]
        try:
            yield self
        finally:
            for cls, original in originals.items():
                cls.stream = original  # type: ignore[method-assign]
