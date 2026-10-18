"""[core] 노드마다 이웃 라우팅 테이블을 두고 등록 시 full-mesh 로 잇는 P2P 토폴로지."""

from jarvis.core.multi_agent.protocol import AgentNodeProtocol
from .base import BaseTopology


class P2PTopology(BaseTopology):
    """add_node() 는 기존 노드 전부와 양방향으로 잇는다. connect() / disconnect() 로 라우팅을 명시적으로 제어한다."""

    def __init__(self) -> None:
        super().__init__()
        self._routing: dict[str, list[str]] = {}  # name → [neighbor_names]

    # ── 노드 등록 ──────────────────────────────────────────────────────────────

    def add_node(self, node: AgentNodeProtocol) -> None:
        """멱등 + 기존 노드와 full-mesh 자동 연결."""
        if node.name in self._nodes:
            return
        existing_names = list(self._nodes.keys())
        super().add_node(node)
        # 신규 ↔ 기존 양방향 연결
        self._routing[node.name] = existing_names[:]
        for name in existing_names:
            self._routing.setdefault(name, [])
            if node.name not in self._routing[name]:
                self._routing[name].append(node.name)

    # ── 라우팅 제어 ────────────────────────────────────────────────────────────

    def connect(
        self, from_name: str, to_name: str, bidirectional: bool = True
    ) -> None:
        self._routing.setdefault(from_name, [])
        if to_name not in self._routing[from_name]:
            self._routing[from_name].append(to_name)
        if bidirectional:
            self._routing.setdefault(to_name, [])
            if from_name not in self._routing[to_name]:
                self._routing[to_name].append(from_name)

    def disconnect(
        self, from_name: str, to_name: str, bidirectional: bool = True
    ) -> None:
        if from_name in self._routing:
            self._routing[from_name] = [
                n for n in self._routing[from_name] if n != to_name
            ]
        if bidirectional and to_name in self._routing:
            self._routing[to_name] = [
                n for n in self._routing[to_name] if n != from_name
            ]

    # ── 조회 ──────────────────────────────────────────────────────────────────

    def get_neighbors(self, name: str) -> list[AgentNodeProtocol]:
        neighbor_names = self._routing.get(name, [])
        return [self._nodes[n] for n in neighbor_names if n in self._nodes]
