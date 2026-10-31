"""multi_agent: 노드, 토폴로지, 오케스트레이터 기반 클래스의 기본 동작과 구현체 상속을 검증한다."""

import pytest

from jarvis.core.multi_agent import (
    AgentNode,
    AgentNodeProtocol,
    AgentResult,
    AgentTask,
    LazyAgentNode,
    OrchestratorProtocol,
    TopologyProtocol,
)
from jarvis.core.multi_agent.topologies import BlackboardTopology, HierarchicalTopology, P2PTopology, SupervisorTopology
from jarvis.core.multi_agent.topologies.topology_base import BaseTopology


class Node(AgentNodeProtocol):
    def __init__(self, name: str) -> None:
        self.name = name
        self.capabilities = []

    async def invoke(self, task: AgentTask) -> AgentResult:
        return AgentResult(task_id=task.task_id, agent_name=self.name, content=f"{self.name}:{task.content}")


@pytest.mark.parametrize("protocol", [AgentNodeProtocol(), OrchestratorProtocol()])
async def test_protocol_has_no_default_work_method(protocol):
    method = protocol.invoke if isinstance(protocol, AgentNodeProtocol) else protocol.dispatch

    with pytest.raises(NotImplementedError):
        await method(AgentTask.create("x"))


@pytest.mark.parametrize("node", [Node("a"), AgentNode("a", session=object())])
async def test_can_handle_defaults_true(node):
    assert await node.can_handle(AgentTask.create("anything")) is True


def test_node_implementations_inherit_protocol():
    assert issubclass(AgentNode, AgentNodeProtocol)
    assert issubclass(LazyAgentNode, AgentNodeProtocol)
    assert isinstance(AgentNode("a", session=object()), AgentNodeProtocol)


def test_add_node_first_registration_wins():
    topo = TopologyProtocol()
    first, second = Node("a"), Node("a")

    topo.add_node(first)
    topo.add_node(second)

    assert topo.get_node("a") is first
    assert topo.get_nodes() == [first]
    assert topo.get_node("nope") is None


def test_get_neighbors_defaults_to_all_other_nodes():
    topo = TopologyProtocol()
    a, b, c = Node("a"), Node("b"), Node("c")
    for n in (a, b, c):
        topo.add_node(n)

    assert topo.get_neighbors("a") == [b, c]


@pytest.mark.parametrize("cls", [BlackboardTopology, HierarchicalTopology, P2PTopology, SupervisorTopology])
def test_topology_implementations_inherit_bases(cls):
    assert isinstance(cls(), TopologyProtocol)
    assert isinstance(cls(), BaseTopology)
