"""[core] 여러 오케스트레이터를 순차 합성해 앞 단계 결과를 다음 단계 입력으로 넘기는 fail-fast 파이프라인."""

from jarvis.core.multi_agent.multi_agent_protocol import OrchestratorProtocol
from jarvis.core.multi_agent.task import AgentResult, AgentTask
from .orchestrator_base import BaseOrchestrator


class OrchestratorPipeline(OrchestratorProtocol):
    """실패(success=False) 시 즉시 중단. 패턴 조합 예: Hierarchical(계획) → Blackboard(실행) → Supervisor(검증)."""

    def __init__(self, orchestrators: list[BaseOrchestrator]) -> None:
        if not orchestrators:
            raise ValueError("Pipeline requires at least one orchestrator.")
        self.orchestrators = orchestrators

    async def dispatch(self, task: AgentTask) -> AgentResult:
        current_task = task
        last_result: AgentResult | None = None

        for orchestrator in self.orchestrators:
            result = await orchestrator.dispatch(current_task)
            last_result = result

            if not result.success:
                return result  # fail-fast

            # 이전 단계 결과를 다음 단계 입력으로
            current_task = AgentTask.create(
                content=result.content,
                context={
                    **current_task.context,
                    "previous_result": result.content,
                    "previous_agent": result.agent_name,
                },
                parent_task_id=task.task_id,  # 원본 부모 유지
                scope=task.scope,
            )

        assert last_result is not None
        return last_result
