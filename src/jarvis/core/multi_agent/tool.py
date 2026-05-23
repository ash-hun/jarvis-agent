"""AgentNodeTool — AgentNode를 JarvisTool로 노출.

기존 ToolRegistry.register()에 그대로 꽂힌다.
오케스트레이터 AgentSession의 tool_registry에 등록하면
LLM이 tool_call로 sub-agent를 호출할 수 있다 (Supervisor 패턴).
"""

from __future__ import annotations

import asyncio
from typing import Any

from jarvis.model_layer.types import TextContent, ToolResultMessage

from .node import AgentNode
from .task import AgentTask


class AgentNodeTool:
    """JarvisTool Protocol을 구현하는 sub-agent 래퍼."""

    execution_mode: str = "sequential"

    def __init__(self, node: AgentNode) -> None:
        self._node = node
        self.name = f"agent_{node.name}"
        caps = ", ".join(node.capabilities) if node.capabilities else "general"
        self.description = (
            f"Delegate a task to the '{node.name}' sub-agent. "
            f"Capabilities: {caps}."
        )
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

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
    ) -> ToolResultMessage:
        task = AgentTask.create(content=params["task"])
        result = await self._node.invoke(task)
        text = result.content if result.success else f"[agent error] {result.error}"
        return ToolResultMessage(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            content=[TextContent(type="text", text=text)],
            is_error=not result.success,
        )
