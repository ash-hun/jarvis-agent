from __future__ import annotations

import time
from typing import Protocol, runtime_checkable

from jarvis.agent_layer.openloop.types import OpenLoop, normalize_description


@runtime_checkable
class OpenLoopStore(Protocol):
    """open-loop 저장소 — 교체 가능(in_memory / postgres 등).

    LTM과 달리 상태 변경(open→done/dismissed)이 잦아 전용 update API를 제공한다.
    """

    async def add(self, loop: OpenLoop) -> str: ...

    async def add_unique(self, loop: OpenLoop) -> str | None: ...

    async def list_open(self, session_id: str | None = None, limit: int = 20) -> list[OpenLoop]: ...

    async def get(self, loop_id: str) -> OpenLoop | None: ...

    async def update_status(self, loop_id: str, status: str) -> bool: ...

    async def all(self) -> list[OpenLoop]: ...


class InMemoryOpenLoopStore:
    """테스트·로컬용 in-memory 구현. 프로세스 재시작 시 소멸(영속화는 후속)."""

    def __init__(self) -> None:
        self._loops: dict[str, OpenLoop] = {}

    async def add(self, loop: OpenLoop) -> str:
        self._loops[loop.id] = loop
        return loop.id

    async def add_unique(self, loop: OpenLoop) -> str | None:
        """같은 세션의 열린 항목 중 설명이 중복이면 추가하지 않고 None 반환."""
        key = normalize_description(loop.description)
        if not key:
            return None
        for existing in self._loops.values():
            if (
                existing.status == "open"
                and existing.origin_session == loop.origin_session
                and normalize_description(existing.description) == key
            ):
                return None
        return await self.add(loop)

    async def list_open(self, session_id: str | None = None, limit: int = 20) -> list[OpenLoop]:
        items = [
            x
            for x in self._loops.values()
            if x.status == "open" and (session_id is None or x.origin_session == session_id)
        ]
        items.sort(key=lambda x: x.created_at, reverse=True)
        return items[:limit]

    async def get(self, loop_id: str) -> OpenLoop | None:
        return self._loops.get(loop_id)

    async def update_status(self, loop_id: str, status: str) -> bool:
        loop = self._loops.get(loop_id)
        if loop is None or status not in ("open", "done", "dismissed"):
            return False
        loop.status = status  # type: ignore[assignment]
        loop.updated_at = int(time.time() * 1000)
        return True

    async def all(self) -> list[OpenLoop]:
        return list(self._loops.values())
