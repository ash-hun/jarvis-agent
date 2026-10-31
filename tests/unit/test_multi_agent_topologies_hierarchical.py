"""multi_agent: HierarchicalTopology 의 레벨 묶음, 부모 자식 조회, 멱등 등록, 강제 교체를 검증한다."""

import pytest
from unittest.mock import MagicMock

from jarvis.core.multi_agent.topologies.hierarchical import HierarchicalTopology


def make_node(name: str) -> MagicMock:
    node = MagicMock()
    node.name = name
    node.capabilities = []
    return node


def test_add_node_groups_by_level_and_links_parent():
    topo = HierarchicalTopology()

    topo.add_node(make_node("ctrl"), level=0)
    topo.add_node(make_node("w1"), level=1, parent="ctrl")
    topo.add_node(make_node("w2"), level=1, parent="ctrl")

    assert [n.name for n in topo.get_level(0)] == ["ctrl"]
    assert {n.name for n in topo.get_level(1)} == {"w1", "w2"}
    assert {n.name for n in topo.get_children("ctrl")} == {"w1", "w2"}
    assert topo.get_parent("w1").name == "ctrl"
    assert (topo.level_of("ctrl"), topo.level_of("w2")) == (0, 1)


def test_lookups_for_missing_relations_are_empty():
    topo = HierarchicalTopology()

    topo.add_node(make_node("root"), level=0)

    assert topo.get_children("root") == []
    assert topo.get_parent("root") is None
    assert topo.level_of("ghost") is None


@pytest.mark.parametrize(("levels", "expected"), [([], 0), ([0, 1, 2], 2)])
def test_max_level_is_deepest_level_or_zero(levels, expected):
    topo = HierarchicalTopology()

    for i, level in enumerate(levels):
        topo.add_node(make_node(f"n{i}"), level=level)

    assert topo.max_level() == expected


def test_add_node_ignores_duplicate_name():
    topo = HierarchicalTopology()
    node = make_node("ctrl")

    topo.add_node(node, level=0)
    topo.add_node(node, level=0)

    assert len(topo.get_level(0)) == 1


def test_add_node_force_moves_node_to_new_level():
    topo = HierarchicalTopology()
    topo.add_node(make_node("w"), level=1, parent="ctrl")
    replacement = make_node("w")

    topo.add_node_force(replacement, level=2, parent="ctrl")

    assert topo.get_level(1) == []
    assert topo.get_level(2) == [replacement]
