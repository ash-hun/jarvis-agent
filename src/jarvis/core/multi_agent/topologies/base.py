"""[core] 모든 토폴로지 구현체가 공유하는 노드 관리(강제 교체, 삭제, 크기, 포함 여부)를 제공한다."""

from __future__ import annotations

from jarvis.core.multi_agent.protocol import AgentNodeProtocol, TopologyProtocol


class BaseTopology(TopologyProtocol):
    """add_node() 는 first-registration-wins 멱등 정책. 강제 교체가 필요하면 add_node_force() 를 명시적으로 쓴다."""

    def add_node_force(self, node: AgentNodeProtocol) -> None:
        """기존 동일 name 을 강제 교체."""
        self._nodes[node.name] = node

    def remove_node(self, name: str) -> None:
        self._nodes.pop(name, None)

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, name: str) -> bool:
        return name in self._nodes
