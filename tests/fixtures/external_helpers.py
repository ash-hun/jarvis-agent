"""external 기능 단위 테스트가 함께 쓰는 고정 시계와 이벤트 생성기."""

from jarvis.core.external import ExternalEvent


class Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def event(source: str, key: str, **kw: str) -> ExternalEvent:
    return ExternalEvent(source=source, key=key, **kw)
