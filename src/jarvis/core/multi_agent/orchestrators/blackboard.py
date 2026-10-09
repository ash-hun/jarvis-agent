"""BlackboardOrchestrator — 공유 블랙보드 기반 협업 실행.

1. 초기 task를 블랙보드에 기록
2. 모든 노드가 블랙보드 스냅샷을 context로 받아 병렬 실행
3. 각 노드의 결과를 블랙보드에 기록
4. 전체 결과를 합산하여 반환
"""

from __future__ import annotations

import asyncio
from typing import Any

from jarvis.core.multi_agent.blackboard import SharedBlackboard
from jarvis.core.multi_agent.task import AgentResult, AgentTask
from jarvis.core.multi_agent.topologies.blackboard import BlackboardTopology

from .base import BaseOrchestrator


class BlackboardOrchestrator(BaseOrchestrator):
    def __init__(
        self,
        topology: BlackboardTopology,
        blackboard: SharedBlackboard,
        memory: Any = None,
    ) -> None:
        super().__init__(topology, memory)
        self.blackboard = blackboard
        self._last_scope: Any = None  # promote 가 기본으로 쓸 범위(마지막 dispatch 의 부모 범위)

    async def dispatch(self, task: AgentTask) -> AgentResult:
        # 작업 공표
        await self.blackboard.write("task", task.content, author="orchestrator")
        await self.share(task, f"작업: {task.content}", author="orchestrator")

        # 블랙보드 현재 상태를 context로 주입
        bb_task = AgentTask.create(
            content=task.content,
            context={**task.context, "blackboard": self.blackboard.snapshot()},
            parent_task_id=task.task_id,
            scope=task.scope,
        )

        nodes = self.topology.get_nodes()
        if not nodes:
            return AgentResult(
                task_id=task.task_id,
                agent_name="blackboard_orchestrator",
                content="",
                success=False,
                error="No nodes in topology",
            )

        results: tuple[AgentResult, ...] = await asyncio.gather(
            *[node.invoke(bb_task) for node in nodes]
        )

        # 결과를 블랙보드에 기록
        for node, result in zip(nodes, results, strict=False):
            if result.success:
                await self.blackboard.write(
                    f"result_{node.name}", result.content, author=node.name
                )
                await self.share(task, f"결과: {result.content}", author=node.name)

        successful = [r for r in results if r.success]
        combined = "\n".join(r.content for r in successful)

        return AgentResult(
            task_id=task.task_id,
            agent_name="blackboard_orchestrator",
            content=combined,
            success=bool(successful),
            error=None if successful else "All agents failed",
        )

    async def promote(self, items: list[Any]) -> None:
        """블랙보드의 result_* 항목(또는 지정한 키)을 shared 의미 사실로 올린다. 작업이 끝난 뒤 명시적으로."""
        if self.memory is None:
            return
        keys = [str(k) for k in items] if items else [k for k in self.blackboard.snapshot() if k.startswith("result_")]
        for key in keys:
            entry = self.blackboard.read_entry(key)
            if entry is None or not isinstance(entry.value, str) or not entry.value.strip():
                continue
            await self.memory.remember(
                entry.value,
                source="promoted",
                visibility="shared",
                author=entry.author,
                tags=[f"blackboard:{key}"],
            )
