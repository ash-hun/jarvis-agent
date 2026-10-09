"""평가 대상 어댑터. 실행기는 이 프로토콜만 알고, 어느 저장소를 재는지는 주입으로 정한다."""

from datetime import datetime
from typing import Protocol

from jarvis.memory.eval.schema import SetupStep
from jarvis.memory.manager import MemoryManager
from jarvis.memory.scope import MemoryScope
from jarvis.memory.stores.in_memory import InMemoryItemStore


class EvalTarget(Protocol):
    async def reset(self) -> None: ...

    async def setup(self, step: SetupStep, scope: MemoryScope) -> None: ...

    async def probe(self, query: str, scope: MemoryScope, top_k: int) -> list[str]:
        """scope 에서 query 로 회상한 내용을 점수 순으로 돌려준다."""
        ...


class StoreTarget:
    """jarvis.memory 의 매니저 + in-memory 저장소. 기본 평가 대상."""

    def __init__(self) -> None:
        self._memory = MemoryManager(InMemoryItemStore())

    async def reset(self) -> None:
        await self._memory.clear()

    async def setup(self, step: SetupStep, scope: MemoryScope) -> None:
        await self._memory.remember(
            step.remember,
            source="eval",
            scope=scope,
            kind=step.kind,
            visibility=step.visibility,
            created_at=datetime.fromisoformat(step.at) if step.at else None,
        )

    async def probe(self, query: str, scope: MemoryScope, top_k: int) -> list[str]:
        return [i.content for i in await self._memory.recall(query, scope, limit=top_k)]


TARGETS = {"store": StoreTarget}
