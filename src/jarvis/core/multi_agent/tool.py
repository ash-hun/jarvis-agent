"""AgentNodeTool. 서브 에이전트를 JarvisTool 로 노출해 LLM 이 tool_call 로 위임하게 한다.

두 모드가 있다.
- 정적: 미리 만든 AgentNode 하나(테스트, 단순 배선)
- 지연: AgentDefinition + AgentFactory 를 LazyAgentNode 로 감싼다. 범위 상속과 위임 기록은 노드가 한다.
  부모 범위는 ToolContext 로 받는다. 레지스트리를 거치지 않는 호출(테스트, 정적 배선)은 contextvar 로 폴백.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from jarvis.memory.scope import LOCAL_USER, MemoryScope, current_scope
from jarvis.model_layer.types import TextContent, ToolResultMessage

from .node import AgentNode, LazyAgentNode, record_delegation
from .task import AgentTask

if TYPE_CHECKING:
    from jarvis.memory.manager import MemoryManager

    from .factory import AgentDefinition, AgentFactory


class AgentNodeTool:
    """JarvisTool Protocol을 구현하는 sub-agent 래퍼."""

    execution_mode: str = "sequential"

    def __init__(
        self,
        node: AgentNode | LazyAgentNode | None = None,
        *,
        definition: AgentDefinition | None = None,
        factory: AgentFactory | None = None,
        memory: MemoryManager | None = None,
    ) -> None:
        if node is None:
            if definition is None or factory is None:
                raise ValueError("AgentNodeTool needs a node, or a definition with a factory")
            node = LazyAgentNode(definition, factory, memory)
        self._node = node
        self._memory = memory
        self.name = f"agent_{node.name}"
        caps = ", ".join(node.capabilities) if node.capabilities else "general"
        self.description = f"Delegate a task to the '{node.name}' sub-agent. Capabilities: {caps}."
        self.parameters: dict[str, Any] = {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Task description to delegate to this sub-agent.",
                }
            },
            "required": ["task"],
        }

    @property
    def node(self) -> AgentNode | LazyAgentNode:
        return self._node

    @property
    def agent_name(self) -> str:
        return self._node.name

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
        context: Any = None,
    ) -> ToolResultMessage:
        parent_scope = getattr(context, "scope", None) or current_scope.get() or MemoryScope(user_id=LOCAL_USER)
        task = AgentTask.create(content=params["task"], scope=parent_scope)
        result = await self._node.invoke(task)
        if not isinstance(self._node, LazyAgentNode):
            # 정적 노드는 스스로 기록하지 않는다
            await record_delegation(self._memory, parent_scope, self.agent_name, task, result)
        text = result.content if result.success else f"[agent error] {result.error}"
        return ToolResultMessage(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            content=[TextContent(type="text", text=text)],
            is_error=not result.success,
        )
