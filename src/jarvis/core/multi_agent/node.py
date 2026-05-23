"""AgentNode — AgentSession을 멱등한 그래프 노드로 래핑.

ResultCache가 동일 task_id의 재호출을 막아 멱등성을 보장한다.
session은 Any로 받아 circular import를 피한다 (AgentSession은 core에 있음).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .task import AgentResult, AgentTask

if TYPE_CHECKING:
    from jarvis.core.session import AgentSession


class ResultCache:
    """task_id → AgentResult 캐시. 동일 task_id 재실행 시 세션 호출 없이 반환."""

    def __init__(self) -> None:
        self._store: dict[str, AgentResult] = {}

    def get(self, task_id: str) -> AgentResult | None:
        return self._store.get(task_id)

    def set(self, task_id: str, result: AgentResult) -> None:
        self._store[task_id] = result

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


class AgentNode:
    """AgentSession을 감싸는 그래프 노드.

    - invoke(): 멱등 — 동일 task_id는 캐시 반환
    - can_handle(): Market-Based 패턴 입찰용 (기본값 True)
    - capabilities: 이 노드가 잘 처리하는 작업 레이블 (라우팅 힌트)
    """

    def __init__(
        self,
        name: str,
        session: "AgentSession | Any",
        capabilities: list[str] | None = None,
    ) -> None:
        self.name = name
        self.capabilities: list[str] = capabilities or []
        self._session = session
        self._cache = ResultCache()

    async def invoke(self, task: AgentTask) -> AgentResult:
        cached = self._cache.get(task.task_id)
        if cached is not None:
            return cached

        try:
            msg = await self._session.prompt(task.content)
            content = msg.text if msg else ""
            result = AgentResult(
                task_id=task.task_id,
                agent_name=self.name,
                content=content,
                success=True,
            )
        except Exception as exc:
            result = AgentResult(
                task_id=task.task_id,
                agent_name=self.name,
                content="",
                success=False,
                error=str(exc),
            )

        self._cache.set(task.task_id, result)
        return result

    async def can_handle(self, task: AgentTask) -> bool:
        """기본값 True. Market 패턴에서 특화 에이전트는 이를 오버라이드한다."""
        return True

    def clear_cache(self) -> None:
        self._cache.clear()
