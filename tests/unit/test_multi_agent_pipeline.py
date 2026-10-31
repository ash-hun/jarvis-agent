"""multi_agent: OrchestratorPipeline 이 앞 단계 결과를 다음 단계에 넘기고 실패에서 멈추는지 검증한다."""

import pytest
from unittest.mock import MagicMock

from jarvis.core.multi_agent.orchestrators.orchestrator_base import BaseOrchestrator
from jarvis.core.multi_agent.orchestrators.pipeline import OrchestratorPipeline
from jarvis.core.multi_agent.topologies.supervisor import SupervisorTopology
from jarvis.core.multi_agent.task import AgentResult, AgentTask


class EchoOrchestrator(BaseOrchestrator):
    async def dispatch(self, task: AgentTask) -> AgentResult:
        return AgentResult(task_id=task.task_id, agent_name="echo", content=task.content)


def make_stage(response: str = "done", success: bool = True, seen: list | None = None) -> MagicMock:
    orch = MagicMock()

    async def dispatch(task: AgentTask) -> AgentResult:
        if seen is not None:
            seen.append(task)
        return AgentResult(task_id=task.task_id, agent_name="m", content=response, success=success,
                           error=None if success else "boom")

    orch.dispatch = dispatch
    return orch


@pytest.mark.parametrize(
    ("stages", "expected"),
    [
        (lambda: [make_stage("done")], "done"),
        (lambda: [make_stage("plan"), make_stage("execute"), make_stage("validate")], "validate"),
        (lambda: [EchoOrchestrator(SupervisorTopology()) for _ in range(2)], "initial"),
    ],
)
async def test_dispatch_returns_last_stage_result(stages, expected):
    result = await OrchestratorPipeline(stages()).dispatch(AgentTask.create("initial"))

    assert result.success
    assert result.content == expected


async def test_dispatch_feeds_previous_output_and_keeps_original_parent():
    seen: list[AgentTask] = []
    original = AgentTask.create("initial")

    await OrchestratorPipeline([make_stage("stage1_out", seen=seen), make_stage("stage2_out", seen=seen)]).dispatch(
        original
    )

    assert [t.content for t in seen] == ["initial", "stage1_out"]
    assert [t.parent_task_id for t in seen] == [None, original.task_id]


async def test_dispatch_stops_at_first_failure():
    seen: list[AgentTask] = []

    result = await OrchestratorPipeline([make_stage(success=False), make_stage(seen=seen)]).dispatch(
        AgentTask.create("task")
    )

    assert not result.success
    assert seen == []


def test_pipeline_requires_a_stage():
    with pytest.raises(ValueError):
        OrchestratorPipeline([])
