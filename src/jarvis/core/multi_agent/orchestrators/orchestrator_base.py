"""[core] 모든 오케스트레이터가 공유하는 토폴로지 보관, 작업 공유 메모리 전달, 승격 자리를 제공한다."""

from typing import Any

from jarvis.core.multi_agent.multi_agent_protocol import OrchestratorProtocol, TopologyProtocol
from jarvis.core.multi_agent.task import AgentTask


class BaseOrchestrator(OrchestratorProtocol):
    """memory 가 있으면 에이전트 간 결과 전달을 작업 공유 메모리(MemoryService.share)로 한다.

    자식 세션의 observe 가 같은 루트 task_id 의 메모를 [작업 공유 메모리] 블록으로 주입하므로,
    task.context 에만 넣던 이전 방식과 달리 결과가 실제로 다음 에이전트의 프롬프트에 도달한다.
    dispatch() 는 OrchestratorProtocol 에서 물려받아 패턴마다 오버라이드한다.
    """

    # memory 는 MemoryService 또는 같은 share/remember 를 가진 테스트 더블. 순환 import 를 피해 Any
    def __init__(self, topology: TopologyProtocol, memory: Any = None) -> None:
        self.topology = topology
        self.memory = memory

    async def share(self, task: AgentTask, text: str, author: str) -> None:
        if self.memory is None:
            return
        root = task.parent_task_id or task.task_id
        await self.memory.share(root, text, author, scope=task.scope)

    # items 는 패턴마다 다른 키(블랙보드 키 등), scope 는 MemoryScope. 기반은 해석하지 않아 Any
    async def promote(self, items: list[Any], scope: Any = None) -> None:
        """작업 중 공유 메모리(블랙보드)의 항목을 공유 장기 기억으로 올리는 자리. 기본은 아무것도 안 한다."""
        return None
