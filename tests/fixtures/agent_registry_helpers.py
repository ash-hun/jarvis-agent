"""agent_registry 테스트가 같이 쓰는, 이름만 가진 도구와 그 도구로 채운 레지스트리."""

import asyncio
from typing import Any

from jarvis.core.tools.tools_registry import JarvisTool, ToolContext, ToolRegistry
from jarvis.model_layer.model_types import ToolResultMessage


class Named(JarvisTool):
    def __init__(self, name: str) -> None:
        self.name, self.description, self.parameters = name, name, {"type": "object"}

    async def execute(self, tool_call_id: str, params: dict[str, Any], signal: asyncio.Event | None = None,
                      context: ToolContext | None = None) -> ToolResultMessage:
        return ToolResultMessage(tool_call_id=tool_call_id, tool_name=self.name, content=[], final=True)


def app_tools(*names: str) -> ToolRegistry:
    registry = ToolRegistry()
    for name in names:
        registry.register(Named(name))
    return registry
