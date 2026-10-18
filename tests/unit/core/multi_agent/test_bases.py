"""multi-agent 기반 클래스(protocol, topologies.base, orchestrators.base)의 기본 동작 테스트."""

import pytest

from jarvis.core.multi_agent import (
    AgentNode,
    AgentNodeProtocol,
    AgentResult,
    AgentTask,
    BlackboardOrchestrator,
    HierarchicalOrchestrator,
    LazyAgentNode,
    MarketOrchestrator,
    OrchestratorPipeline,
    OrchestratorProtocol,
    SupervisorOrchestrator,
    TopologyProtocol,
)
from jarvis.core.multi_agent.topologies import BlackboardTopology, HierarchicalTopology, P2PTopology, SupervisorTopology
from jarvis.core.multi_agent.orchestrators.base import BaseOrchestrator
from jarvis.core.multi_agent.topologies.base import BaseTopology


class Node(AgentNodeProtocol):
    def __init__(self, name: str) -> None:
        self.name = name
        self.capabilities = []

    async def invoke(self, task: AgentTask) -> AgentResult:
        return AgentResult(task_id=task.task_id, agent_name=self.name, content=f"{self.name}:{task.content}")


class EchoOrchestrator(BaseOrchestrator):
    async def dispatch(self, task: AgentTask) -> AgentResult:
        return AgentResult(task_id=task.task_id, agent_name="echo", content=task.content)


class FakeMemory:
    def __init__(self) -> None:
        self.shared: list[tuple] = []

    async def share(self, root, text, author, scope=None):
        self.shared.append((root, text, author, scope))


class TestAgentNodeProtocol:
    async def test_invoke_has_no_default(self):
        with pytest.raises(NotImplementedError):
            await AgentNodeProtocol().invoke(AgentTask.create("x"))

    async def test_can_handle_defaults_true(self):
        assert await Node("a").can_handle(AgentTask.create("anything")) is True

    def test_implementations_inherit(self):
        assert issubclass(AgentNode, AgentNodeProtocol)
        assert issubclass(LazyAgentNode, AgentNodeProtocol)
        assert isinstance(AgentNode("a", session=object()), AgentNodeProtocol)


class TestTopologyProtocol:
    def test_add_node_first_registration_wins(self):
        topo = TopologyProtocol()
        first, second = Node("a"), Node("a")
        topo.add_node(first)
        topo.add_node(second)
        assert topo.get_node("a") is first
        assert topo.get_nodes() == [first]

    def test_get_node_missing_is_none(self):
        assert TopologyProtocol().get_node("nope") is None

    def test_neighbors_are_all_others(self):
        topo = TopologyProtocol()
        a, b, c = Node("a"), Node("b"), Node("c")
        for n in (a, b, c):
            topo.add_node(n)
        assert topo.get_neighbors("a") == [b, c]

    @pytest.mark.parametrize("cls", [BlackboardTopology, HierarchicalTopology, P2PTopology, SupervisorTopology])
    def test_implementations_inherit(self, cls):
        assert isinstance(cls(), TopologyProtocol)
        assert isinstance(cls(), BaseTopology)


class TestBaseTopology:
    def test_add_node_force_replaces(self):
        topo = BaseTopology()
        first, second = Node("a"), Node("a")
        topo.add_node(first)
        topo.add_node_force(second)
        assert topo.get_node("a") is second

    def test_remove_node_is_idempotent(self):
        topo = BaseTopology()
        topo.add_node(Node("a"))
        topo.remove_node("a")
        topo.remove_node("a")
        assert len(topo) == 0
        assert "a" not in topo

    def test_len_and_contains(self):
        topo = BaseTopology()
        topo.add_node(Node("a"))
        topo.add_node(Node("b"))
        assert len(topo) == 2
        assert "a" in topo


class TestOrchestratorBases:
    async def test_protocol_dispatch_has_no_default(self):
        with pytest.raises(NotImplementedError):
            await OrchestratorProtocol().dispatch(AgentTask.create("x"))

    async def test_base_dispatch_has_no_default(self):
        with pytest.raises(NotImplementedError):
            await BaseOrchestrator(SupervisorTopology()).dispatch(AgentTask.create("x"))

    async def test_share_without_memory_is_noop(self):
        await EchoOrchestrator(SupervisorTopology()).share(AgentTask.create("x"), "t", "me")

    async def test_share_uses_root_task_id(self):
        memory = FakeMemory()
        orch = EchoOrchestrator(SupervisorTopology(), memory=memory)
        child = AgentTask.create("x", parent_task_id="root")
        await orch.share(child, "note", "me")
        orphan = AgentTask.create("y")
        await orch.share(orphan, "note2", "me")
        assert memory.shared == [("root", "note", "me", None), (orphan.task_id, "note2", "me", None)]

    async def test_promote_default_does_nothing(self):
        assert await EchoOrchestrator(SupervisorTopology()).promote(["k"]) is None

    def test_implementations_inherit(self):
        for cls in (
            BlackboardOrchestrator,
            HierarchicalOrchestrator,
            MarketOrchestrator,
            SupervisorOrchestrator,
        ):
            assert issubclass(cls, BaseOrchestrator)
            assert issubclass(cls, OrchestratorProtocol)
        pipeline = OrchestratorPipeline([EchoOrchestrator(SupervisorTopology())])
        assert isinstance(pipeline, OrchestratorProtocol)

    async def test_pipeline_of_base_subclasses(self):
        stages: list[BaseOrchestrator] = [EchoOrchestrator(SupervisorTopology()) for _ in range(2)]
        pipeline = OrchestratorPipeline(stages)
        result = await pipeline.dispatch(AgentTask.create("hello"))
        assert result.content == "hello"
