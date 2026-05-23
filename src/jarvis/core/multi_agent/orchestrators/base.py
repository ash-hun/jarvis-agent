"""BaseOrchestrator — 모든 오케스트레이터의 공통 기반."""

from __future__ import annotations

from abc import ABC, abstractmethod

from jarvis.core.multi_agent.protocol import TopologyProtocol
from jarvis.core.multi_agent.task import AgentResult, AgentTask


class BaseOrchestrator(ABC):
    def __init__(self, topology: TopologyProtocol) -> None:
        self.topology = topology

    @abstractmethod
    async def dispatch(self, task: AgentTask) -> AgentResult: ...
