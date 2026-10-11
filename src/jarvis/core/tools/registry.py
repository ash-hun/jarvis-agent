"""[core] 도구의 기반 클래스(JarvisTool)와 이름으로 등록, 조회, 실행하는 ToolRegistry 를 제공한다."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any

from jarvis.model_layer.types import TextContent, Tool, ToolResultMessage


@dataclass(frozen=True)
class ToolContext:
    """도구를 부른 세션의 정보. 서브 에이전트 위임처럼 '누가 불렀는가'가 필요한 도구가 쓴다."""

    scope: Any  # MemoryScope. 순환 import 를 피해 Any
    session_id: str | None = None
    user_id: str | None = None


# 기반을 상속하지 않은 덕 타이핑 도구(사용자 디렉터리 도구, 테스트 더블)도 받으므로 Any
def accepts_context(tool: Any) -> bool:
    try:
        return "context" in inspect.signature(tool.execute).parameters
    except (TypeError, ValueError):
        return False


class JarvisTool:
    """모든 툴의 기반. name, description, parameters 는 도구마다 정하고 execute 를 오버라이드한다.

    ToolRegistry 는 상속하지 않았어도 같은 모양(이름, 설명, 스키마, 실행 모드, execute)이면 받는다.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    execution_mode: str = "parallel"  # "parallel" | "sequential"

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
    ) -> ToolResultMessage:
        raise NotImplementedError("도구마다 하는 일이 달라 기본 실행이 없다")


class ToolRegistry:
    """툴 등록/조회/삭제 레지스트리. first-registration-wins 정책. Pi: SkillsManager + AgentTool 패턴."""

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
                execution_mode=t.execution_mode,
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
                # context 를 받는 도구만 이 분기로 온다(accepts_context 가 런타임에 확인). 기반 시그니처에는 없다
                return await tool.execute(tool_call_id, params, signal, context=context)  # type: ignore[call-arg]
            return await tool.execute(tool_call_id, params, signal)
        except Exception as exc:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=[TextContent(text=f"Tool execution error: {exc}")],
                is_error=True,
            )
