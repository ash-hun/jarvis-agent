"""평가 대상 어댑터. 실행기는 이 프로토콜만 알고, 어느 저장소를 재는지는 주입으로 정한다."""

from datetime import datetime
from typing import Protocol

from jarvis.memory.eval.schema import SetupStep
from jarvis.memory.scope import MemoryScope


class EvalTarget(Protocol):
    async def reset(self) -> None: ...

    async def setup(self, step: SetupStep, scope: MemoryScope) -> None: ...

    async def probe(self, query: str, scope: MemoryScope, top_k: int) -> list[str]:
        """scope 에서 query 로 회상한 내용을 점수 순으로 돌려준다."""
        ...


class LegacyLTMTarget:
    """현재 구조(agent_layer.memory 의 LTM 백엔드). 베이스라인 측정용.

    search 가 scope 를 받지 않으므로 scope 는 저장 시 metadata 에만 남고 검색엔 쓰이지 않는다.
    격리 스위트가 여기서 실패하는 것이 0단계의 기대 결과다.
    """

    def __init__(self) -> None:
        from jarvis.agent_layer.memory.backends.in_memory_ltm import InMemoryLTMBackend

        self._backend = InMemoryLTMBackend()

    async def reset(self) -> None:
        await self._backend.clear_all()

    async def setup(self, step: SetupStep, scope: MemoryScope) -> None:
        from jarvis.agent_layer.memory.backends.protocol import MemoryEntry

        entry = MemoryEntry(
            content=step.remember,
            source="explicit",
            session_id=scope.session_id,
            metadata={"user_id": scope.user_id, "agent_id": scope.agent_id, "visibility": step.visibility},
        )
        if step.at:
            entry.created_at = datetime.fromisoformat(step.at)
        await self._backend.store(entry)

    async def probe(self, query: str, scope: MemoryScope, top_k: int) -> list[str]:
        return [e.content for e in await self._backend.search(query, limit=top_k)]


TARGETS = {"legacy": LegacyLTMTarget}
