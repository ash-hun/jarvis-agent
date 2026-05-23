"""BaseTopology — 모든 토폴로지 구현체의 공통 기반.

add_node()는 first-registration-wins 멱등 정책.
강제 교체가 필요하면 add_node_force()를 명시적으로 사용.
"""

from __future__ import annotations

from jarvis.core.multi_agent.protocol import AgentNodeProtocol


class BaseTopology:
    def __init__(self) -> None:
        self._nodes: dict[str, AgentNodeProtocol] = {}

    # ── 노드 관리 (멱등) ───────────────────────────────────────────────────────

    def add_node(self, node: AgentNodeProtocol) -> None:
        """이미 등록된 name이면 무시 (first-registration-wins)."""
        if node.name not in self._nodes:
            self._nodes[node.name] = node

    def add_node_force(self, node: AgentNodeProtocol) -> None:
        """기존 동일 name을 강제 교체."""
        self._nodes[node.name] = node

    def remove_node(self, name: str) -> None:
        self._nodes.pop(name, None)

    # ── 조회 ──────────────────────────────────────────────────────────────────

    def get_node(self, name: str) -> AgentNodeProtocol | None:
        return self._nodes.get(name)

    def get_nodes(self) -> list[AgentNodeProtocol]:
        return list(self._nodes.values())

    def get_neighbors(self, name: str) -> list[AgentNodeProtocol]:
        """기본값: 자신을 제외한 모든 노드. P2PTopology가 오버라이드."""
        return [n for n in self._nodes.values() if n.name != name]

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, name: str) -> bool:
        return name in self._nodes
