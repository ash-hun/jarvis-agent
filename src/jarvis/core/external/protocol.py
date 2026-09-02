from __future__ import annotations

from typing import Protocol, runtime_checkable

from jarvis.core.external.types import ExternalEvent


@runtime_checkable
class ExternalSource(Protocol):
    """주기적으로 외부 세계를 한 번 훑어 이벤트 목록을 돌려주는 소스.

    Protocol이므로 MCP가 아닌 소스(웹훅·파일 감시·사내 API)도 같은 자리에 꽂힌다.
    poll()은 예외를 던지지 않는 것을 권장한다(폴러도 격리하지만 소스 단위가 우선).
    """

    name: str
    interval_sec: float

    async def poll(self) -> list[ExternalEvent]: ...
