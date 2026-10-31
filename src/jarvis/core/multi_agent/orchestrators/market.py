"""[core] 모든 노드의 입찰(can_handle, score)을 받아 가장 높은 priority 노드 하나에 작업을 맡기는 오케스트레이터."""

import asyncio
from typing import Any
from dataclasses import dataclass, field

from jarvis.core.multi_agent.multi_agent_protocol import AgentNodeProtocol, TopologyProtocol
from jarvis.core.multi_agent.task import AgentResult, AgentTask
from .orchestrator_base import BaseOrchestrator


@dataclass
class Bid:
    node: AgentNodeProtocol
    can_handle: bool
    priority: float = field(default=1.0)


class MarketOrchestrator(BaseOrchestrator):
    """priority 를 재정의하려면 Bid 를 반환하는 _collect_bids() 를 서브클래스에서 오버라이드한다."""

    def __init__(self, topology: TopologyProtocol, memory: Any = None) -> None:
        super().__init__(topology, memory)

    async def _collect_bids(self, task: AgentTask) -> list[Bid]:
        """can_handle 로 입찰 여부, score(있으면) 로 우선순위. 점수가 없는 노드는 1.0."""
        nodes = self.topology.get_nodes()
        results = await asyncio.gather(*[node.can_handle(task) for node in nodes])
        bids: list[Bid] = []
        for node, can in zip(nodes, results, strict=False):
            scorer = getattr(node, "score", None)
            priority = float(scorer(task)) if callable(scorer) else 1.0
            bids.append(Bid(node=node, can_handle=can, priority=priority))
        return bids

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
