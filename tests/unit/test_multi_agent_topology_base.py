"""multi_agent: BaseTopology 의 강제 교체, 삭제, 크기와 포함 여부를 검증한다."""

import pytest
from unittest.mock import MagicMock

from jarvis.core.multi_agent.topologies.supervisor import SupervisorTopology
from jarvis.core.multi_agent.topologies.topology_base import BaseTopology


def make_node(name: str) -> MagicMock:
    node = MagicMock()
    node.name = name
    node.capabilities = []
    return node


@pytest.mark.parametrize("cls", [BaseTopology, SupervisorTopology])
def test_add_node_force_replaces_existing(cls):
    topo = cls()
    first, second = make_node("a"), make_node("a")
    topo.add_node(first)

    topo.add_node_force(second)

    assert topo.get_node("a") is second
    assert len(topo) == 1


def test_remove_node_is_idempotent():
    topo = BaseTopology()
    topo.add_node(make_node("a"))

    topo.remove_node("a")
    topo.remove_node("a")
    topo.remove_node("ghost")

    assert len(topo) == 0
    assert "a" not in topo


def test_len_and_contains_reflect_registered_nodes():
    topo = SupervisorTopology()

    topo.add_node(make_node("a"))
    topo.add_node(make_node("b"))

    assert len(topo) == 2
    assert {n.name for n in topo.get_nodes()} == {"a", "b"}
    assert "a" in topo
    assert "c" not in topo
