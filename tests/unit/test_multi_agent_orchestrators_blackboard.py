"""multi_agent: BlackboardOrchestrator 가 작업과 성공 결과를 블랙보드에 쓰고 스냅샷을 노드에 넘기는지 검증한다."""

from unittest.mock import MagicMock

from jarvis.core.multi_agent.orchestrators.blackboard import BlackboardOrchestrator
from jarvis.core.multi_agent.topologies.blackboard import BlackboardTopology
from jarvis.core.multi_agent.blackboard import SharedBlackboard
from jarvis.core.multi_agent.task import AgentResult, AgentTask


def make_node(name: str, content: str = "ok", success: bool = True, seen: list | None = None) -> MagicMock:
    node = MagicMock()
    node.name = name
    node.capabilities = []

    async def invoke(task: AgentTask) -> AgentResult:
        if seen is not None:
            seen.append(task)
        return AgentResult(task_id=task.task_id, agent_name=name, content=content, success=success,
                           error=None if success else "forced error")

    node.invoke = invoke
    return node


async def test_dispatch_writes_task_and_successful_results():
    bb = SharedBlackboard()
    topo = BlackboardTopology()
    topo.add_node(make_node("researcher", "research_output"))
    topo.add_node(make_node("broken", "err", success=False))

    await BlackboardOrchestrator(topo, bb).dispatch(AgentTask.create("my task"))

    assert bb.read("task") == "my task"
    assert bb.read("result_researcher") == "research_output"
    assert bb.read("result_broken") is None


async def test_dispatch_injects_blackboard_snapshot_into_context():
    seen: list[AgentTask] = []
    bb = SharedBlackboard()
    await bb.write("prior_data", "existing", author="system")
    topo = BlackboardTopology()
    topo.add_node(make_node("solver", "solved", seen=seen))

    await BlackboardOrchestrator(topo, bb).dispatch(AgentTask.create("task"))

    assert seen[0].context["blackboard"].get("prior_data") == "existing"


async def test_dispatch_on_empty_topology_fails():
    result = await BlackboardOrchestrator(BlackboardTopology(), SharedBlackboard()).dispatch(AgentTask.create("task"))

    assert not result.success
