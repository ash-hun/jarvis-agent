"""Topology 단위 테스트 — 멱등성 / 계층 구조 / 라우팅 검증."""

from unittest.mock import MagicMock

from jarvis.core.multi_agent.topologies.hierarchical import HierarchicalTopology
from jarvis.core.multi_agent.topologies.p2p import P2PTopology
from jarvis.core.multi_agent.topologies.supervisor import SupervisorTopology

# ── 헬퍼 ──────────────────────────────────────────────────────────────────────


def make_node(name: str) -> MagicMock:
    node = MagicMock()
    node.name = name
    node.capabilities = []
    return node


# ══════════════════════════════════════════════════════════════════════════════
# SupervisorTopology
# ══════════════════════════════════════════════════════════════════════════════


class TestSupervisorTopology:
    def test_add_node_idempotent(self):
        topo = SupervisorTopology()
        node = make_node("a")
        topo.add_node(node)
        topo.add_node(node)
        assert len(topo) == 1

    def test_add_different_nodes(self):
        topo = SupervisorTopology()
        topo.add_node(make_node("a"))
        topo.add_node(make_node("b"))
        assert len(topo) == 2

    def test_get_node_exists(self):
        topo = SupervisorTopology()
        node = make_node("researcher")
        topo.add_node(node)
        assert topo.get_node("researcher") is node

    def test_get_node_missing(self):
        assert SupervisorTopology().get_node("ghost") is None

    def test_remove_node(self):
        topo = SupervisorTopology()
        topo.add_node(make_node("a"))
        topo.remove_node("a")
        assert len(topo) == 0

    def test_remove_nonexistent_is_noop(self):
        topo = SupervisorTopology()
        topo.remove_node("ghost")  # 예외 없음

    def test_get_nodes_returns_all(self):
        topo = SupervisorTopology()
        topo.add_node(make_node("a"))
        topo.add_node(make_node("b"))
        names = {n.name for n in topo.get_nodes()}
        assert names == {"a", "b"}

    def test_add_node_force_replaces(self):
        topo = SupervisorTopology()
        n1 = make_node("agent")
        n2 = make_node("agent")
        topo.add_node(n1)
        topo.add_node_force(n2)
        assert topo.get_node("agent") is n2

    def test_contains(self):
        topo = SupervisorTopology()
        topo.add_node(make_node("a"))
        assert "a" in topo
        assert "b" not in topo


# ══════════════════════════════════════════════════════════════════════════════
# HierarchicalTopology
# ══════════════════════════════════════════════════════════════════════════════


class TestHierarchicalTopology:
    def test_level_grouping(self):
        topo = HierarchicalTopology()
        topo.add_node(make_node("ctrl"), level=0)
        topo.add_node(make_node("w1"), level=1, parent="ctrl")
        topo.add_node(make_node("w2"), level=1, parent="ctrl")

        assert len(topo.get_level(0)) == 1
        assert len(topo.get_level(1)) == 2

    def test_max_level(self):
        topo = HierarchicalTopology()
        topo.add_node(make_node("l0"), level=0)
        topo.add_node(make_node("l1"), level=1)
        topo.add_node(make_node("l2"), level=2)
        assert topo.max_level() == 2

    def test_max_level_empty(self):
        assert HierarchicalTopology().max_level() == 0

    def test_get_children(self):
        topo = HierarchicalTopology()
        topo.add_node(make_node("ctrl"), level=0)
        topo.add_node(make_node("w1"), level=1, parent="ctrl")
        topo.add_node(make_node("w2"), level=1, parent="ctrl")

        names = {n.name for n in topo.get_children("ctrl")}
        assert names == {"w1", "w2"}

    def test_get_children_no_children(self):
        topo = HierarchicalTopology()
        topo.add_node(make_node("leaf"), level=0)
        assert topo.get_children("leaf") == []

    def test_get_parent(self):
        topo = HierarchicalTopology()
        topo.add_node(make_node("ctrl"), level=0)
        topo.add_node(make_node("w"), level=1, parent="ctrl")
        assert topo.get_parent("w").name == "ctrl"

    def test_get_parent_root_returns_none(self):
        topo = HierarchicalTopology()
        topo.add_node(make_node("root"), level=0)
        assert topo.get_parent("root") is None

    def test_add_node_idempotent(self):
        topo = HierarchicalTopology()
        node = make_node("ctrl")
        topo.add_node(node, level=0)
        topo.add_node(node, level=0)
        assert len(topo.get_level(0)) == 1

    def test_add_node_force_updates_level(self):
        topo = HierarchicalTopology()
        n1 = make_node("w")
        n2 = make_node("w")
        topo.add_node(n1, level=1, parent="ctrl")
        topo.add_node_force(n2, level=2, parent="ctrl")

        assert topo.get_level(1) == []   # 기존 레벨에서 제거
        assert len(topo.get_level(2)) == 1

    def test_level_of(self):
        topo = HierarchicalTopology()
        topo.add_node(make_node("a"), level=0)
        topo.add_node(make_node("b"), level=1)
        assert topo.level_of("a") == 0
        assert topo.level_of("b") == 1
        assert topo.level_of("ghost") is None


# ══════════════════════════════════════════════════════════════════════════════
# P2PTopology
# ══════════════════════════════════════════════════════════════════════════════


class TestP2PTopology:
    def test_full_mesh_on_add(self):
        topo = P2PTopology()
        topo.add_node(make_node("a"))
        topo.add_node(make_node("b"))
        topo.add_node(make_node("c"))

        a_neighbors = {n.name for n in topo.get_neighbors("a")}
        assert a_neighbors == {"b", "c"}

    def test_symmetric_connections(self):
        topo = P2PTopology()
        topo.add_node(make_node("a"))
        topo.add_node(make_node("b"))

        assert {n.name for n in topo.get_neighbors("a")} == {"b"}
        assert {n.name for n in topo.get_neighbors("b")} == {"a"}

    def test_add_node_idempotent(self):
        topo = P2PTopology()
        node = make_node("a")
        topo.add_node(node)
        topo.add_node(node)
        assert len(topo) == 1
        assert len(topo.get_neighbors("a")) == 0

    def test_explicit_connect(self):
        topo = P2PTopology()
        topo.add_node(make_node("a"))
        topo.add_node(make_node("b"))
        topo.add_node(make_node("c"))
        # 라우팅 초기화 후 수동 연결
        topo._routing = {"a": [], "b": [], "c": []}
        topo.connect("a", "b")

        assert {n.name for n in topo.get_neighbors("a")} == {"b"}
        assert {n.name for n in topo.get_neighbors("b")} == {"a"}
        assert topo.get_neighbors("c") == []

    def test_disconnect(self):
        topo = P2PTopology()
        topo.add_node(make_node("a"))
        topo.add_node(make_node("b"))

        topo.disconnect("a", "b")

        assert topo.get_neighbors("a") == []
        assert topo.get_neighbors("b") == []

    def test_connect_unidirectional(self):
        topo = P2PTopology()
        topo.add_node(make_node("a"))
        topo.add_node(make_node("b"))
        topo._routing = {"a": [], "b": []}

        topo.connect("a", "b", bidirectional=False)

        assert {n.name for n in topo.get_neighbors("a")} == {"b"}
        assert topo.get_neighbors("b") == []

    def test_single_node_no_neighbors(self):
        topo = P2PTopology()
        topo.add_node(make_node("solo"))
        assert topo.get_neighbors("solo") == []
