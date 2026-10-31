"""multi_agent: P2PTopology 의 full-mesh 자동 연결과 connect, disconnect 라우팅을 검증한다."""

import pytest
from unittest.mock import MagicMock

from jarvis.core.multi_agent.topologies.p2p import P2PTopology


def make_node(name: str) -> MagicMock:
    node = MagicMock()
    node.name = name
    node.capabilities = []
    return node


def neighbors(topo: P2PTopology, name: str) -> set[str]:
    return {n.name for n in topo.get_neighbors(name)}


def test_add_node_connects_new_node_to_all_existing_both_ways():
    topo = P2PTopology()

    for name in ("a", "b", "c"):
        topo.add_node(make_node(name))

    assert neighbors(topo, "a") == {"b", "c"}
    assert neighbors(topo, "b") == {"a", "c"}
    assert neighbors(topo, "c") == {"a", "b"}


def test_add_node_ignores_duplicate_name():
    topo = P2PTopology()
    node = make_node("a")

    topo.add_node(node)
    topo.add_node(node)

    assert len(topo) == 1
    assert topo.get_neighbors("a") == []


def test_disconnect_removes_link_both_ways():
    topo = P2PTopology()
    topo.add_node(make_node("a"))
    topo.add_node(make_node("b"))

    topo.disconnect("a", "b")

    assert topo.get_neighbors("a") == []
    assert topo.get_neighbors("b") == []


@pytest.mark.parametrize(("bidirectional", "b_sees_a"), [(True, True), (False, False)])
def test_connect_adds_link_in_requested_directions(bidirectional, b_sees_a):
    topo = P2PTopology()
    for name in ("a", "b", "c"):
        topo.add_node(make_node(name))
    for x, y in (("a", "b"), ("a", "c"), ("b", "c")):
        topo.disconnect(x, y)

    topo.connect("a", "b", bidirectional=bidirectional)

    assert neighbors(topo, "a") == {"b"}
    assert neighbors(topo, "b") == ({"a"} if b_sees_a else set())
    assert topo.get_neighbors("c") == []
