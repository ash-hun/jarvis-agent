"""HierarchicalOrchestrator — 레벨 순서 직렬, 동일 레벨 병렬 실행.

각 레벨의 누적 결과가 다음 레벨의 context로 주입되어
상위 에이전트의 판단이 하위 에이전트에 전달된다.
"""

from __future__ import annotations

import asyncio

from jarvis.core.multi_agent.task import AgentResult, AgentTask
from jarvis.core.multi_agent.topologies.hierarchical import HierarchicalTopology

from .base import BaseOrchestrator


class HierarchicalOrchestrator(BaseOrchestrator):
    def __init__(self, topology: HierarchicalTopology) -> None:
        super().__init__(topology)

    async def dispatch(self, task: AgentTask) -> AgentResult:
        topo: HierarchicalTopology = self.topology  # type: ignore[assignment]
        accumulated: dict = dict(task.context)
        last_results: list[AgentResult] = []

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
                parent_task_id=task.task_id,
            )

            # 동일 레벨: 병렬 실행
            results: tuple[AgentResult, ...] = await asyncio.gather(
                *[node.invoke(level_task) for node in nodes]
            )
            last_results = list(results)

            # 다음 레벨용 context 누적
            for node, result in zip(nodes, results, strict=False):
                accumulated[f"result_{node.name}"] = result.content

        if not last_results:
            return AgentResult(
                task_id=task.task_id,
                agent_name="hierarchical_orchestrator",
                content="",
                success=False,
                error="No nodes in topology",
            )

        combined = "\n".join(r.content for r in last_results if r.success)
        success = all(r.success for r in last_results)
        return AgentResult(
            task_id=task.task_id,
            agent_name="hierarchical_orchestrator",
            content=combined,
            success=success,
            error=next((r.error for r in last_results if not r.success), None),
        )
