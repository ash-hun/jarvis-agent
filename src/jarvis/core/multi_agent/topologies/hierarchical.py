"""[core] 노드를 레벨(0 = 루트, 같은 레벨은 병렬 실행)과 부모로 묶는 트리 토폴로지."""

from __future__ import annotations

from jarvis.core.multi_agent.protocol import AgentNodeProtocol

from .base import BaseTopology


class HierarchicalTopology(BaseTopology):
    """레벨 0 = 루트(controller), 레벨 1 = 1차 하위. 동일 레벨 노드는 HierarchicalOrchestrator 에서 병렬 실행된다."""

    def __init__(self) -> None:
        super().__init__()
        self._levels: dict[int, list[str]] = {}       # level → [node_name, ...]
        self._parent_map: dict[str, str] = {}          # child_name → parent_name

    # ── 노드 등록 ──────────────────────────────────────────────────────────────

    def add_node(
        self,
        node: AgentNodeProtocol,
        level: int = 0,
        parent: str | None = None,
    ) -> None:
        """멱등. 동일 name 재등록은 무시."""
        if node.name in self._nodes:
            return
        super().add_node(node)
        self._levels.setdefault(level, [])
        if node.name not in self._levels[level]:
            self._levels[level].append(node.name)
        if parent:
            self._parent_map[node.name] = parent

    def add_node_force(
        self,
        node: AgentNodeProtocol,
        level: int = 0,
        parent: str | None = None,
    ) -> None:
        """기존 동일 name을 강제 교체 (레벨/부모 정보도 갱신)."""
        # 기존 항목 제거
        if node.name in self._nodes:
            for lvl_nodes in self._levels.values():
                if node.name in lvl_nodes:
                    lvl_nodes.remove(node.name)
            self._parent_map.pop(node.name, None)
        self._nodes[node.name] = node
        self._levels.setdefault(level, [])
        if node.name not in self._levels[level]:
            self._levels[level].append(node.name)
        if parent:
            self._parent_map[node.name] = parent

    # ── 계층 조회 ──────────────────────────────────────────────────────────────

    def get_level(self, level: int) -> list[AgentNodeProtocol]:
        names = self._levels.get(level, [])
        return [self._nodes[n] for n in names if n in self._nodes]

    def get_children(self, parent_name: str) -> list[AgentNodeProtocol]:
        return [
            self._nodes[child]
            for child, p in self._parent_map.items()
            if p == parent_name and child in self._nodes
        ]

    def get_parent(self, child_name: str) -> AgentNodeProtocol | None:
        parent_name = self._parent_map.get(child_name)
        return self._nodes.get(parent_name) if parent_name else None

    def max_level(self) -> int:
        return max(self._levels.keys(), default=0)

    def level_of(self, name: str) -> int | None:
        for lvl, names in self._levels.items():
            if name in names:
                return lvl
        return None
