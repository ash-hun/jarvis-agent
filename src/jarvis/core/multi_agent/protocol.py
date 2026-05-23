"""Multi-agent 아키텍처의 핵심 계약.

이 파일만 안정되면 Topology / Orchestrator / Node 는 독립적으로 교체·확장 가능하다.
모든 구현체는 이 Protocol을 만족해야 한다.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .task import AgentResult, AgentTask


@runtime_checkable
class AgentNodeProtocol(Protocol):
    """단일 에이전트 노드의 계약.

    어떤 topology / orchestration 패턴에도 참여 가능한 최소 인터페이스.
    can_handle()은 Market-Based 패턴에서 입찰 여부를 결정하는 데 쓰인다.
    """

    name: str
    capabilities: list[str]

    async def invoke(self, task: AgentTask) -> AgentResult: ...

    async def can_handle(self, task: AgentTask) -> bool: ...


@runtime_checkable
class TopologyProtocol(Protocol):
    """에이전트 간 연결 방식의 계약.

    add_node()는 멱등 — 동일 name 재등록은 무시(first-registration-wins).
    강제 교체가 필요하면 add_node_force()를 쓴다.
    """

    def add_node(self, node: AgentNodeProtocol) -> None: ...

    def get_node(self, name: str) -> AgentNodeProtocol | None: ...

    def get_nodes(self) -> list[AgentNodeProtocol]: ...

    def get_neighbors(self, name: str) -> list[AgentNodeProtocol]: ...


@runtime_checkable
class OrchestratorProtocol(Protocol):
    """작업 분배 방식의 계약.

    dispatch()는 외부 상태를 변경하지 않는 순수 함수에 가깝게 유지한다.
    OrchestratorPipeline이 여러 orchestrator를 동일하게 취급하기 위해 이 Protocol을 사용.
    """

    async def dispatch(self, task: AgentTask) -> AgentResult: ...
