"""AgentNodeTool. 서브 에이전트를 JarvisTool 로 노출해 LLM 이 tool_call 로 위임하게 한다.

두 모드가 있다.
- 정적: 미리 만든 AgentNode 하나(테스트, 단순 배선)
- 지연: AgentDefinition + AgentFactory. 위임 시점의 부모 범위(current_scope)로 자식 세션을 정하고,
  부모 범위에 위임 기록(일화)을 남긴다. 부모 범위는 contextvar 로 받는다. ToolRegistry.execute 에
  컨텍스트 인자가 없기 때문이다. ponytail: 도구 실행에 컨텍스트가 생기면 인자로 받는다
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from jarvis.memory.scope import LOCAL_USER, MemoryScope, current_scope
from jarvis.model_layer.types import TextContent, ToolResultMessage

from .node import AgentNode
from .task import AgentResult, AgentTask

if TYPE_CHECKING:
    from jarvis.memory.manager import MemoryManager

    from .factory import AgentDefinition, AgentFactory

DELEGATION_SOURCE = "delegation"
TASK_PREVIEW = 120
RESULT_PREVIEW = 300


class AgentNodeTool:
    """JarvisTool Protocol을 구현하는 sub-agent 래퍼."""

    execution_mode: str = "sequential"

    def __init__(
        self,
        node: AgentNode | None = None,
        *,
        definition: AgentDefinition | None = None,
        factory: AgentFactory | None = None,
        memory: MemoryManager | None = None,
    ) -> None:
        if node is None and (definition is None or factory is None):
            raise ValueError("AgentNodeTool needs a node, or a definition with a factory")
        self._node = node
        self._definition = definition
        self._factory = factory
        self._memory = memory
        name = node.name if node is not None else definition.name  # type: ignore[union-attr]
        caps = node.capabilities if node is not None else definition.capabilities  # type: ignore[union-attr]
        self.name = f"agent_{name}"
        self.description = f"Delegate a task to the '{name}' sub-agent. Capabilities: {', '.join(caps) or 'general'}."
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
    def agent_name(self) -> str:
        return self.name.removeprefix("agent_")

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
    ) -> ToolResultMessage:
        parent_scope = current_scope.get() or MemoryScope(user_id=LOCAL_USER)
        task = AgentTask.create(content=params["task"], scope=parent_scope)

        if self._factory is not None and self._definition is not None:
            node, child_scope = await self._factory.node_for(self._definition, parent_scope, task)
            token = current_scope.set(child_scope)
            try:
                result = await node.invoke(task)
            finally:
                current_scope.reset(token)  # 부모 턴의 나머지가 자식 범위로 쓰지 않도록 되돌린다
                await self._factory.release(self._definition, child_scope.session_id or "")
        else:
            assert self._node is not None
            result = await self._node.invoke(task)

        await self._record_delegation(parent_scope, task, result)
        text = result.content if result.success else f"[agent error] {result.error}"
        return ToolResultMessage(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            content=[TextContent(type="text", text=text)],
            is_error=not result.success,
        )

    async def _record_delegation(self, parent_scope: MemoryScope, task: AgentTask, result: AgentResult) -> None:
        """부모가 "무엇을 누구에게 맡겼고 어떻게 됐는지" 를 일화로 기억한다. 저장 실패는 위임 결과를 깨지 않는다."""
        if self._memory is None:
            return
        outcome = result.content if result.success else f"실패: {result.error}"
        content = (
            f"위임: {self.agent_name} 에게 '{_clip(task.content, TASK_PREVIEW)}' 를 맡김. "
            f"결과: {_clip(outcome, RESULT_PREVIEW)}"
        )
        try:
            await self._memory.remember(
                content,
                source=DELEGATION_SOURCE,
                scope=parent_scope,
                tags=[f"agent:{self.agent_name}"],
                metadata={"agent": self.agent_name, "task_id": task.task_id, "success": result.success},
            )
        except Exception:
            return


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
