"""[core] 노드, 토폴로지, 오케스트레이터의 기반 클래스로 multi-agent 계약과 기본 동작을 정한다."""

from __future__ import annotations

from .task import AgentResult, AgentTask


class AgentNodeProtocol:
    """단일 에이전트 노드의 기반. 어떤 topology / orchestration 패턴에도 참여 가능한 최소 인터페이스.

    can_handle() 은 Market-Based 패턴에서 입찰 여부를 결정하는 데 쓰인다.
    """

    name: str
    capabilities: list[str]

    async def invoke(self, task: AgentTask) -> AgentResult:
        raise NotImplementedError("노드마다 작업을 수행하는 방식(세션, 팩토리)이 달라 기본 구현이 없다")

    async def can_handle(self, task: AgentTask) -> bool:
        """기본값 True. Market 패턴에서 특화 에이전트는 이를 오버라이드한다."""
        return True


class TopologyProtocol:
    """에이전트 간 연결 방식의 기반. 기본은 이름 → 노드 사전 하나인 flat 구조.

    add_node() 는 멱등이다. 동일 name 재등록은 무시(first-registration-wins).
    강제 교체가 필요하면 BaseTopology.add_node_force() 를 쓴다.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, AgentNodeProtocol] = {}

    def add_node(self, node: AgentNodeProtocol) -> None:
        """이미 등록된 name 이면 무시 (first-registration-wins)."""
        if node.name not in self._nodes:
            self._nodes[node.name] = node

    def get_node(self, name: str) -> AgentNodeProtocol | None:
        return self._nodes.get(name)

    def get_nodes(self) -> list[AgentNodeProtocol]:
        return list(self._nodes.values())

    def get_neighbors(self, name: str) -> list[AgentNodeProtocol]:
        """기본값: 자신을 제외한 모든 노드. P2PTopology 가 오버라이드."""
        return [n for n in self._nodes.values() if n.name != name]


class OrchestratorProtocol:
    """작업 분배 방식의 기반. OrchestratorPipeline 이 여러 orchestrator 를 동일하게 취급하려고 쓴다.

    dispatch() 는 외부 상태를 변경하지 않는 순수 함수에 가깝게 유지한다.
    """

    async def dispatch(self, task: AgentTask) -> AgentResult:
        raise NotImplementedError("작업 분배 방식이 곧 오케스트레이터의 정체라 기본 구현이 없다")
