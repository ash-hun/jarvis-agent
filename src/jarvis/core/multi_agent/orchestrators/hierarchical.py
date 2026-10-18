"""[core] 레벨 순서는 직렬, 같은 레벨은 병렬로 실행하고 누적 결과를 다음 레벨 context 로 넘기는 오케스트레이터."""

import asyncio
from typing import Any

from jarvis.core.multi_agent.topologies.hierarchical import HierarchicalTopology
from jarvis.core.multi_agent.task import AgentResult, AgentTask
from .base import BaseOrchestrator


class HierarchicalOrchestrator(BaseOrchestrator):
    """각 레벨의 누적 결과가 다음 레벨의 context 로 주입되어 상위 에이전트의 판단이 하위 에이전트에 전달된다."""

    def __init__(self, topology: HierarchicalTopology, memory: Any = None) -> None:
        super().__init__(topology, memory)

    async def dispatch(self, task: AgentTask) -> AgentResult:
        topo: HierarchicalTopology = self.topology  # type: ignore[assignment]
        accumulated: dict[str, Any] = dict(task.context)
        last_results: list[AgentResult] = []

        failures: list[AgentResult] = []
        for level in range(topo.max_level() + 1):
            nodes = topo.get_level(level)
            if not nodes:
                continue

            # 이전 레벨 결과를 context로 주입
            level_task = AgentTask.create(
                content=task.content,
                context={
                    **accumulated,
                    "level": level,
                    "previous_results": [r.content for r in last_results],
                },
                parent_task_id=task.parent_task_id or task.task_id,  # 루트 작업을 공유 키로 유지
                scope=task.scope,
            )

            # 동일 레벨: 병렬 실행
            results: list[AgentResult] = await asyncio.gather(
                *[node.invoke(level_task) for node in nodes]
            )
            last_results = list(results)
            # 앞 레벨의 실패도 최종 결과에 남긴다. 마지막 레벨만 보면 중간 실패가 성공으로 보고된다
            failures.extend(r for r in results if not r.success)
            # 다음 레벨용 context 누적 + 작업 공유 메모리(다음 레벨 에이전트의 프롬프트에 실제로 들어간다)
            for node, result in zip(nodes, results, strict=False):
                accumulated[f"result_{node.name}"] = result.content
                if result.success:
                    await self.share(task, f"level {level} 결과: {result.content}", author=node.name)

        if not last_results:
            return AgentResult(
                task_id=task.task_id,
                agent_name="hierarchical_orchestrator",
                content="",
                success=False,
                error="No nodes in topology",
            )

        combined = "\n".join(r.content for r in last_results if r.success)
        success = not failures
        return AgentResult(
            task_id=task.task_id,
            agent_name="hierarchical_orchestrator",
            content=combined,
            success=success,
            error=next((r.error for r in failures), None),
        )
