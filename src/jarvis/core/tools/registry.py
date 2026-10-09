from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from jarvis.model_layer.types import TextContent, Tool, ToolResultMessage


@dataclass(frozen=True)
class ToolContext:
    """도구를 부른 세션의 정보. 서브 에이전트 위임처럼 '누가 불렀는가'가 필요한 도구가 쓴다."""

    scope: Any  # MemoryScope. 순환 import 를 피해 Any
    session_id: str | None = None
    user_id: str | None = None


def accepts_context(tool: Any) -> bool:
    try:
        return "context" in inspect.signature(tool.execute).parameters
    except (TypeError, ValueError):
        return False


@runtime_checkable
class JarvisTool(Protocol):
    """모든 툴이 구현해야 할 Protocol."""
    name: str
    description: str
    parameters: dict[str, Any]
    execution_mode: str  # "parallel" | "sequential"

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
    ) -> ToolResultMessage: ...


class ToolRegistry:
    """
    툴 등록/조회/삭제 레지스트리.
    first-registration-wins 정책.
    Pi: SkillsManager + AgentTool 패턴.
    """

    def __init__(self) -> None:
        self._tools: dict[str, JarvisTool] = {}

    def register(self, tool: JarvisTool) -> None:
        if tool.name not in self._tools:
            self._tools[tool.name] = tool

    def register_force(self, tool: JarvisTool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> JarvisTool | None:
        return self._tools.get(name)

    def list_all(self) -> list[JarvisTool]:
        return list(self._tools.values())

    def to_llm_tools(self) -> list[Tool]:
        return [
            Tool(
                name=t.name,
                description=t.description,
                parameters=t.parameters,
                execution_mode=t.execution_mode,  # type: ignore[arg-type]
            )
            for t in self._tools.values()
        ]

    async def execute(
        self,
        tool_call_id: str,
        tool_name: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
        context: ToolContext | None = None,
    ) -> ToolResultMessage:
        """context 는 호출한 세션의 정보(메모리 범위 등). execute 가 context 인자를 받는 도구에만 넘긴다."""
        tool = self.get(tool_name)
        if tool is None:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=[TextContent(text=f"Tool '{tool_name}' not found")],
                is_error=True,
            )
        try:
            if context is not None and accepts_context(tool):
                return await tool.execute(tool_call_id, params, signal, context=context)
            return await tool.execute(tool_call_id, params, signal)
        except Exception as exc:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=[TextContent(text=f"Tool execution error: {exc}")],
                is_error=True,
            )
