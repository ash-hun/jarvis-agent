"""[memory] 평가 중 provider 의 stream 을 감싸 LLM 호출 횟수를 세는 비용 계측."""

from typing import Any
from dataclasses import dataclass
from collections.abc import Iterator
from contextlib import contextmanager


@dataclass
class CallCounter:
    calls: int = 0


@contextmanager
def count_llm_calls(provider_name: str) -> Iterator[CallCounter]:
    """레지스트리에 등록된 provider 의 stream 호출 수를 센다. 빠져나오면 원래대로 되돌린다."""
    from jarvis.model_layer.registry import get_default_registry

    provider = get_default_registry().get(provider_name)
    counter = CallCounter()
    original = provider.stream

    # provider 마다 stream 시그니처가 달라 인자와 반환값을 그대로 넘긴다
    def counted(*args: Any, **kwargs: Any) -> Any:
        counter.calls += 1
        return original(*args, **kwargs)

    provider.stream = counted  # type: ignore[method-assign]
    try:
        yield counter
    finally:
        provider.stream = original  # type: ignore[method-assign]
