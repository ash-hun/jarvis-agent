"""multi_agent: BaseOrchestrator 의 작업 공유 메모리 전달, 기본 승격, 구현체 상속을 검증한다."""

import pytest

from jarvis.core.multi_agent import (
    AgentResult,
    AgentTask,
    BlackboardOrchestrator,
    HierarchicalOrchestrator,
    MarketOrchestrator,
    OrchestratorPipeline,
    OrchestratorProtocol,
    SupervisorOrchestrator,
)
from jarvis.core.multi_agent.orchestrators.orchestrator_base import BaseOrchestrator
from jarvis.core.multi_agent.topologies import SupervisorTopology


class EchoOrchestrator(BaseOrchestrator):
    async def dispatch(self, task: AgentTask) -> AgentResult:
        return AgentResult(task_id=task.task_id, agent_name="echo", content=task.content)


class FakeMemory:
    def __init__(self) -> None:
        self.shared: list[tuple] = []

    async def share(self, root, text, author, scope=None):
        self.shared.append((root, text, author, scope))


async def test_dispatch_has_no_default():
    with pytest.raises(NotImplementedError):
        await BaseOrchestrator(SupervisorTopology()).dispatch(AgentTask.create("x"))


async def test_share_keys_notes_by_root_task_id():
    memory = FakeMemory()
    orch = EchoOrchestrator(SupervisorTopology(), memory=memory)
    child = AgentTask.create("x", parent_task_id="root")
    orphan = AgentTask.create("y")

    await orch.share(child, "note", "me")
    await orch.share(orphan, "note2", "me")

    assert memory.shared == [("root", "note", "me", None), (orphan.task_id, "note2", "me", None)]


async def test_share_and_promote_without_memory_do_nothing():
    orch = EchoOrchestrator(SupervisorTopology())

    await orch.share(AgentTask.create("x"), "t", "me")

    assert await orch.promote(["k"]) is None


@pytest.mark.parametrize(
    "cls", [BlackboardOrchestrator, HierarchicalOrchestrator, MarketOrchestrator, SupervisorOrchestrator]
)
def test_orchestrator_implementations_inherit_bases(cls):
    assert issubclass(cls, BaseOrchestrator)
    assert issubclass(cls, OrchestratorProtocol)


def test_pipeline_is_an_orchestrator_protocol():
    assert isinstance(OrchestratorPipeline([EchoOrchestrator(SupervisorTopology())]), OrchestratorProtocol)
