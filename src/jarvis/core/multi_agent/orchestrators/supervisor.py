"""SupervisorOrchestrator — LLM이 tool_call로 sub-agent를 선택.

노드를 AgentNodeTool로 래핑해 orchestrator_session의 ToolRegistry에 등록.
LLM이 어떤 에이전트를 언제 쓸지 직접 결정하는 Supervisor 패턴.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jarvis.core.multi_agent.task import AgentResult, AgentTask
from jarvis.core.multi_agent.tool import AgentNodeTool
from jarvis.core.multi_agent.topologies.supervisor import SupervisorTopology

from .base import BaseOrchestrator

if TYPE_CHECKING:
    from jarvis.core.session import AgentSession


class SupervisorOrchestrator(BaseOrchestrator):
    """Supervisor 패턴: 오케스트레이터 세션에 sub-agent를 도구로 노출."""

    def __init__(
        self,
        topology: SupervisorTopology,
        orchestrator_session: AgentSession | Any,
        memory: Any = None,
    ) -> None:
        super().__init__(topology, memory)
        self._session = orchestrator_session
        self._registered: set[str] = set()

    def sync_agents(self) -> None:
        """topology 노드 → ToolRegistry 동기화 (멱등)."""
        for node in self.topology.get_nodes():
            if node.name not in self._registered:
                tool = AgentNodeTool(node, memory=self.memory)
                register = getattr(self._session, "register_tool", None)
                if callable(register):
                    register(tool)  # AgentSession: 레지스트리와 harness 도구 목록을 같이 갱신
                else:
                    self._session.tool_registry.register(tool)
                self._registered.add(node.name)

    async def dispatch(self, task: AgentTask) -> AgentResult:
        self.sync_agents()
        msg = await self._session.prompt(task.content)
        text = getattr(msg, "text", "") if msg else ""
        content = text() if callable(text) else (text or "")  # AssistantMessage.text 는 메서드
        return AgentResult(
            task_id=task.task_id,
            agent_name="supervisor",
            content=content,
            success=True,
        )
