"""multi_agent: HierarchicalOrchestrator 의 레벨 순서, 같은 레벨 병렬, 결과 전달, 실패 전파를 검증한다."""

import time
import pytest
import asyncio
from unittest.mock import MagicMock

from jarvis.core.multi_agent.orchestrators.hierarchical import HierarchicalOrchestrator
from jarvis.core.multi_agent.topologies.hierarchical import HierarchicalTopology
from jarvis.core.multi_agent.task import AgentResult, AgentTask


def make_node(name, content=None, success=True, delay=0.0, seen=None):
    node = MagicMock()
    node.name = name
    node.capabilities = []

    async def invoke(task: AgentTask) -> AgentResult:
        if seen is not None:
            seen.append((name, task))
        await asyncio.sleep(delay)
        return AgentResult(task_id=task.task_id, agent_name=name, content=content or name, success=success,
                           error=None if success else f"{name} failed")

    node.invoke = invoke
    return node


async def test_dispatch_runs_levels_in_order_and_passes_previous_results():
    seen: list = []
    topo = HierarchicalTopology()
    topo.add_node(make_node("ctrl", "plan_output", seen=seen), level=0)
    topo.add_node(make_node("worker", seen=seen), level=1, parent="ctrl")

    result = await HierarchicalOrchestrator(topo).dispatch(AgentTask.create("task"))

    assert [name for name, _ in seen] == ["ctrl", "worker"]
    assert "plan_output" in seen[1][1].context["previous_results"]
    assert result.success


async def test_dispatch_runs_same_level_in_parallel():
    topo = HierarchicalTopology()
    topo.add_node(make_node("w1", delay=0.05), level=0)
    topo.add_node(make_node("w2", delay=0.05), level=0)

    start = time.monotonic()
    result = await HierarchicalOrchestrator(topo).dispatch(AgentTask.create("parallel"))
    elapsed = time.monotonic() - start

    assert elapsed < 0.09  # 직렬이면 0.10s
    assert result.success


@pytest.mark.parametrize(
    ("layout", "error", "content"),
    [
        ([("ok", 0, True), ("broken", 0, False)], "broken failed", "ok"),
        ([("planner", 0, False), ("writer", 1, True)], "planner failed", "writer"),
    ],
)
async def test_dispatch_reports_failure_from_any_level(layout, error, content):
    topo = HierarchicalTopology()
    for name, level, success in layout:
        topo.add_node(make_node(name, success=success), level=level)

    result = await HierarchicalOrchestrator(topo).dispatch(AgentTask.create("task"))

    assert not result.success
    assert result.error == error
    assert result.content == content


async def test_dispatch_on_empty_topology_fails():
    result = await HierarchicalOrchestrator(HierarchicalTopology()).dispatch(AgentTask.create("task"))

    assert not result.success
