"""BaseOrchestrator — 모든 오케스트레이터의 공통 기반."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from jarvis.core.multi_agent.protocol import TopologyProtocol
from jarvis.core.multi_agent.task import AgentResult, AgentTask


class BaseOrchestrator(ABC):
    def __init__(self, topology: TopologyProtocol) -> None:
        self.topology = topology

    @abstractmethod
    async def dispatch(self, task: AgentTask) -> AgentResult: ...

    async def promote(self, items: list[Any]) -> None:
        """작업 중 공유 메모리(블랙보드)의 항목을 공유 장기 기억으로 올리는 자리. 기본은 아무것도 안 한다."""
        return None
