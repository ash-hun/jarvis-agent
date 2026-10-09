"""MarketOrchestrator — 입찰 기반 작업 할당.

모든 노드에게 can_handle()로 입찰을 받고, 가장 높은 priority를 가진 노드가 작업을 수행.
priority를 재정의하려면 Bid를 반환하는 _collect_bids()를 서브클래스에서 오버라이드.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from jarvis.core.multi_agent.protocol import AgentNodeProtocol, TopologyProtocol
from jarvis.core.multi_agent.task import AgentResult, AgentTask

from .base import BaseOrchestrator


@dataclass
class Bid:
    node: AgentNodeProtocol
    can_handle: bool
    priority: float = field(default=1.0)


class MarketOrchestrator(BaseOrchestrator):
    def __init__(self, topology: TopologyProtocol) -> None:
        super().__init__(topology)

    async def _collect_bids(self, task: AgentTask) -> list[Bid]:
        nodes = self.topology.get_nodes()
        results = await asyncio.gather(*[node.can_handle(task) for node in nodes])
        return [Bid(node=node, can_handle=can) for node, can in zip(nodes, results, strict=False)]

    def _select_winner(self, bids: list[Bid]) -> AgentNodeProtocol | None:
        eligible = [b for b in bids if b.can_handle]
        if not eligible:
            return None
        return max(eligible, key=lambda b: b.priority).node

    async def dispatch(self, task: AgentTask) -> AgentResult:
        bids = await self._collect_bids(task)
        winner = self._select_winner(bids)

        if winner is None:
            return AgentResult(
                task_id=task.task_id,
                agent_name="market_orchestrator",
                content="",
                success=False,
                error="No agent available to handle this task",
            )

        return await winner.invoke(task)
