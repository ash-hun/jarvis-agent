"""AgentNode. AgentSession 을 멱등한 그래프 노드로 감싼다.

- AgentNode: 이미 만들어진 세션 하나(정적 배선, 테스트)
- LazyAgentNode: 정의 + 팩토리. 위임 시점의 부모 범위로 자식 세션을 정하고, 위임 동안 메모리 범위와
  작업 공유 키를 contextvar 로 바꿨다 되돌리며, 끝나면 부모 범위에 위임 기록을 남긴다.
  네 오케스트레이션 패턴과 AgentNodeTool 이 전부 이 하나를 거친다(메모리 결합점).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from jarvis.agent_layer.types import AgentEvent
from jarvis.memory.scope import LOCAL_USER, MemoryScope, current_scope, current_task
from jarvis.memory.stores.protocol import tokens_of

from .task import AgentResult, AgentTask

if TYPE_CHECKING:
    from jarvis.core.session import AgentSession
    from jarvis.memory.manager import MemoryManager

    from .factory import AgentDefinition, AgentFactory

AgentEventSink = Callable[[AgentEvent], Awaitable[None]]
DELEGATION_SOURCE = "delegation"
TASK_PREVIEW = 120
RESULT_PREVIEW = 300


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


def capability_score(task: AgentTask, name: str, capabilities: list[str]) -> float:
    """Market 입찰 점수. 작업 문구의 토큰과 이름, capabilities 의 겹침 수. 0 이면 입찰하지 않는다."""
    tokens = set(tokens_of(task.content))
    labels = {name.lower(), *(c.lower() for c in capabilities)}
    return float(sum(1 for t in tokens if t in labels or any(t in c for c in labels if len(c) >= 3)))


async def record_delegation(
    memory: MemoryManager | None, parent_scope: MemoryScope, agent_name: str, task: AgentTask, result: AgentResult
) -> None:
    """부모가 "무엇을 누구에게 맡겼고 어떻게 됐는지" 를 일화로 기억한다. 저장 실패는 위임 결과를 깨지 않는다."""
    if memory is None:
        return
    outcome = result.content if result.success else f"실패: {result.error}"
    content = (
        f"위임: {agent_name} 에게 '{_clip(task.content, TASK_PREVIEW)}' 를 맡김. "
        f"결과: {_clip(outcome, RESULT_PREVIEW)}"
    )
    try:
        await memory.remember(
            content,
            source=DELEGATION_SOURCE,
            scope=parent_scope,
            tags=[f"agent:{agent_name}"],
            metadata={"agent": agent_name, "task_id": task.task_id, "success": result.success},
        )
    except Exception:
        return


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class AgentNode:
    """AgentSession을 감싸는 그래프 노드.

    - invoke(): 멱등 — 동일 task_id는 캐시 반환
    - can_handle(): Market-Based 패턴 입찰용 (기본값 True)
    - capabilities: 이 노드가 잘 처리하는 작업 레이블 (라우팅 힌트)
    """

    def __init__(
        self,
        name: str,
        session: AgentSession | Any,
        capabilities: list[str] | None = None,
        event_sink: AgentEventSink | None = None,
    ) -> None:
        self.name = name
        self.capabilities: list[str] = capabilities or []
        self._session = session
        self._event_sink = event_sink
        self._cache = ResultCache()
        # 세션이 agent_name을 지원하면 자동으로 이름 주입
        if hasattr(session, "agent_name"):
            session.agent_name = name

    async def invoke(self, task: AgentTask) -> AgentResult:
        cached = self._cache.get(task.task_id)
        if cached is not None:
            return cached

        # event_sink가 주어진 경우 서브 에이전트 이벤트를 부모로 포워딩
        unsub = None
        if self._event_sink is not None and hasattr(self._session, "subscribe"):
            unsub = self._session.subscribe(self._event_sink)

        try:
            msg = await self._session.prompt(task.content)
            # AssistantMessage.text 는 메서드다. 테스트 더블은 문자열 속성을 줄 수 있어 둘 다 받는다
            text = getattr(msg, "text", "") if msg else ""
            content = text() if callable(text) else (text or "")
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
        finally:
            if unsub is not None:
                unsub()

        self._cache.set(task.task_id, result)
        return result

    async def can_handle(self, task: AgentTask) -> bool:
        """기본값 True. Market 패턴에서 특화 에이전트는 이를 오버라이드한다."""
        return True

    def clear_cache(self) -> None:
        self._cache.clear()


class LazyAgentNode:
    """정의 + 팩토리로 위임 시점에 자식 세션을 정하는 노드. 범위 상속, 작업 공유 키, 위임 기록을 책임진다."""

    def __init__(
        self,
        definition: AgentDefinition,
        factory: AgentFactory,
        memory: MemoryManager | None = None,
    ) -> None:
        self.definition = definition
        self.factory = factory
        self.memory = memory
        self.name = definition.name
        self.capabilities: list[str] = list(definition.capabilities)

    async def invoke(self, task: AgentTask) -> AgentResult:
        parent_scope = task.scope or current_scope.get() or MemoryScope(user_id=LOCAL_USER)
        node, child_scope = await self.factory.node_for(self.definition, parent_scope, task)
        # 오케스트레이션 안이면 루트 작업(parent_task_id)이 공유 키, 단독 위임이면 자기 작업
        shared_key = task.parent_task_id or task.task_id
        scope_token = current_scope.set(child_scope)
        task_token = current_task.set(shared_key)
        try:
            result = await node.invoke(task)
        finally:
            current_task.reset(task_token)
            current_scope.reset(scope_token)  # 부모 턴의 나머지가 자식 범위로 쓰지 않도록 되돌린다
            await self.factory.release(self.definition, child_scope.session_id or "")
        await record_delegation(self.memory, parent_scope, self.name, task, result)
        return result

    def score(self, task: AgentTask) -> float:
        return capability_score(task, self.name, self.capabilities)

    async def can_handle(self, task: AgentTask) -> bool:
        """capabilities 나 이름이 작업 문구에 등장할 때만 입찰한다. 라벨이 없는 에이전트는 모든 작업에 입찰."""
        return not self.capabilities or self.score(task) > 0
