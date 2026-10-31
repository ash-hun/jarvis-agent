"""multi_agent: MarketOrchestrator 가 입찰한 노드 중 점수가 가장 높은 하나에 맡기는지 검증한다."""

import pytest
from unittest.mock import MagicMock

from jarvis.core.multi_agent.topologies.supervisor import SupervisorTopology
from jarvis.core.multi_agent.orchestrators.market import MarketOrchestrator
from jarvis.core.multi_agent.task import AgentResult, AgentTask


def make_bidder(name: str, can_handle: bool, score: float | None = None) -> MagicMock:
    node = MagicMock(spec=["name", "capabilities", "invoke", "can_handle", "score"] if score is not None
                     else ["name", "capabilities", "invoke", "can_handle"])
    node.name = name
    node.capabilities = []

    async def bid(task: AgentTask) -> bool:
        return can_handle

    async def invoke(task: AgentTask) -> AgentResult:
        return AgentResult(task_id=task.task_id, agent_name=name, content=f"{name}_result")

    node.can_handle = bid
    node.invoke = invoke
    if score is not None:
        node.score = lambda task: score
    return node


@pytest.mark.parametrize(
    ("bidders", "winner"),
    [
        ([("incapable", False, None), ("capable", True, None)], "capable"),
        ([("low", True, 0.3), ("high", True, 0.9)], "high"),
    ],
)
async def test_dispatch_gives_task_to_best_capable_bidder(bidders, winner):
    topo = SupervisorTopology()
    for name, can, score in bidders:
        topo.add_node(make_bidder(name, can, score))

    result = await MarketOrchestrator(topo).dispatch(AgentTask.create("task"))

    assert result.success
    assert (result.agent_name, result.content) == (winner, f"{winner}_result")


@pytest.mark.parametrize("names", [["a", "b"], []])
async def test_dispatch_without_capable_bidder_fails(names):
    topo = SupervisorTopology()
    for name in names:
        topo.add_node(make_bidder(name, False))

    result = await MarketOrchestrator(topo).dispatch(AgentTask.create("task"))

    assert not result.success
    assert result.error is not None
