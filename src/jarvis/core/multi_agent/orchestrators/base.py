"""BaseOrchestrator — 모든 오케스트레이터의 공통 기반."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from jarvis.core.multi_agent.protocol import TopologyProtocol
from jarvis.core.multi_agent.task import AgentResult, AgentTask


class BaseOrchestrator(ABC):
    """memory 가 있으면 에이전트 간 결과 전달을 작업 공유 메모리(MemoryManager.share)로 한다.

    자식 세션의 observe 가 같은 루트 task_id 의 메모를 [작업 공유 메모리] 블록으로 주입하므로,
    task.context 에만 넣던 이전 방식과 달리 결과가 실제로 다음 에이전트의 프롬프트에 도달한다.
    """

    def __init__(self, topology: TopologyProtocol, memory: Any = None) -> None:
        self.topology = topology
        self.memory = memory

    async def share(self, task: AgentTask, text: str, author: str) -> None:
        if self.memory is None:
            return
        root = task.parent_task_id or task.task_id
        await self.memory.share(root, text, author, scope=task.scope)

    @abstractmethod
    async def dispatch(self, task: AgentTask) -> AgentResult: ...

    async def promote(self, items: list[Any], scope: Any = None) -> None:
        """작업 중 공유 메모리(블랙보드)의 항목을 공유 장기 기억으로 올리는 자리. 기본은 아무것도 안 한다."""
        return None
