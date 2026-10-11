"""[core] 에이전트 정의와 부모 범위로 격리된 자식 세션 노드를 만들고 memory.stm 정책대로 수명을 관리한다."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from jarvis.memory.scope import MemoryScope

from .node import AgentNode
from .task import AgentTask

if TYPE_CHECKING:
    from jarvis.agent_layer.types import AgentEvent

StmPolicy = Literal["per_parent_session", "per_task", "per_agent"]
STM_POLICIES: tuple[StmPolicy, ...] = ("per_parent_session", "per_task", "per_agent")


@dataclass(frozen=True)
class AgentMemoryPolicy:
    """에이전트 YAML 의 memory 블록. 지금은 작업 기억(세션) 축만 있다."""

    stm: StmPolicy = "per_parent_session"

    def __post_init__(self) -> None:
        if self.stm not in STM_POLICIES:
            raise ValueError(f"memory.stm must be one of {STM_POLICIES}, got {self.stm!r}")


@dataclass
class AgentDefinition:
    """단일 에이전트 노드 선언."""

    name: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    system_prompt: str | None = None
    tools: list[str] = field(default_factory=list)  # 허용할 builtin tool 이름
    model_override: str | None = None  # None이면 부모 설정 상속
    memory: AgentMemoryPolicy = field(default_factory=AgentMemoryPolicy)
    level: int = 0  # hierarchical 패턴의 레벨. 0 이 먼저, 같은 레벨은 병렬


def child_session_id(definition: AgentDefinition, parent_scope: MemoryScope, task: AgentTask) -> str:
    policy = definition.memory.stm
    if policy == "per_task":
        return f"agent_{definition.name}__task_{task.task_id}"
    if policy == "per_agent":
        return f"agent_{definition.name}"
    return f"agent_{definition.name}__{parent_scope.session_id or 'default'}"


# (정의, 자식 세션 id) → 그 세션으로 돌아가는 AgentSession. startup 이 인프라를 닫아 넣는다
SessionBuilder = Callable[[AgentDefinition, str], Any]


class AgentFactory:
    """AgentDefinition → AgentNode 생성 + 수명 관리.

    자식 세션 id 는 memory.stm 정책이 정한다.
    - per_parent_session: 부모 세션마다 하나. 같은 부모와의 대화는 이어지고, 다른 부모와는 섞이지 않는다
    - per_task: 위임마다 새로 만들고 끝나면 지운다. 도구형 에이전트용
    - per_agent: 에이전트당 하나(범위 도입 전 동작). 모든 부모가 한 이력을 공유한다
    """

    def __init__(
        self,
        event_sink: Callable[[AgentEvent], Awaitable[None]] | None = None,
        build_session: SessionBuilder | None = None,
        session_repo: Any = None,
    ) -> None:
        self._nodes: dict[str, AgentNode] = {}  # 자식 세션 id → 노드
        self._event_sink = event_sink  # sub-agent 이벤트를 부모로 포워딩할 sink
        self._build_session = build_session
        self._session_repo = session_repo

    def create(self, definition: AgentDefinition, base_session: object) -> AgentNode:
        """이미 만들어진 세션을 노드로 감싼다(정적 배선용)."""
        return AgentNode(
            name=definition.name,
            session=base_session,
            capabilities=definition.capabilities,
            event_sink=self._event_sink,
        )

    def get_or_create(self, definition: AgentDefinition, base_session: object) -> AgentNode:
        """멱등. 동일 name이 이미 있으면 캐시 반환."""
        key = f"agent_{definition.name}"
        if key not in self._nodes:
            self._nodes[key] = self.create(definition, base_session)
        return self._nodes[key]

    async def node_for(
        self, definition: AgentDefinition, parent_scope: MemoryScope, task: AgentTask
    ) -> tuple[AgentNode, MemoryScope]:
        """부모 범위와 작업으로 자식 세션을 정하고(필요하면 만들고) 노드와 자식 범위를 돌려준다."""
        if self._build_session is None:
            raise RuntimeError("AgentFactory needs build_session to create child sessions")
        session_id = child_session_id(definition, parent_scope, task)
        child_scope = parent_scope.child(agent_id=definition.name, session_id=session_id)
        node = self._nodes.get(session_id)
        if node is None:
            if self._session_repo is not None:
                await self._session_repo.create(session_id=session_id)
            node = self.create(definition, self._build_session(definition, session_id))
            if definition.memory.stm != "per_task":
                self._nodes[session_id] = node
        return node, child_scope

    async def release(self, definition: AgentDefinition, session_id: str) -> None:
        """per_task 세션은 작업이 끝나면 지운다. 그 밖의 정책은 유지."""
        if definition.memory.stm != "per_task":
            return
        self._nodes.pop(session_id, None)
        if self._session_repo is not None:
            await self._session_repo.delete(session_id)

    def __len__(self) -> int:
        return len(self._nodes)
