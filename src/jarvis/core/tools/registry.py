"""[core] 도구의 기반 클래스(JarvisTool)와 이름으로 등록, 조회, 실행하는 ToolRegistry 를 제공한다."""

import asyncio
import inspect
from typing import Any
from dataclasses import dataclass
from collections.abc import Awaitable, Callable

from jarvis.model_layer.types import TextContent, Tool, ToolResultMessage


@dataclass(frozen=True)
class ToolContext:
    """도구를 부른 세션의 정보. 서브 에이전트 위임처럼 '누가 불렀는가'가 필요한 도구가 쓴다."""

    scope: Any  # MemoryScope. 순환 import 를 피해 Any
    session_id: str | None = None
    user_id: str | None = None
    # 세션의 도구 실행기 (tool_call_id, 도구 이름, 인자). 권한, 플러그인, 승인 검사를 거친다.
    # 다른 도구를 부르는 도구(절차)는 레지스트리가 아니라 이것으로 불러야 검사를 건너뛰지 않는다
    call: Callable[[str, str, dict[str, Any]], Awaitable[ToolResultMessage]] | None = None


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
    # 사용자만 정할 수 있는 값(돈, 조건 등)을 받는 인자. 사람이 없는 차례(목표, 스케줄 작업)에서는 모델이 지어낼 수
    # 있어 버리고 저장된 값으로 돈다
    user_only_params: tuple[str, ...] = ()

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
            for t in self.list_all()
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


class PickedToolRegistry(ToolRegistry):
    """다른 레지스트리에서 이름(이나 접두어)으로 고른 도구만 보이는 창.

    고를 때가 아니라 볼 때 찾으므로 세션을 만든 뒤 등록된 도구(승인된 절차)도 바로 보인다.
    register 로 직접 더한 도구는 이 창에만 있다.
    """

    def __init__(
        self,
        sources: tuple["ToolRegistry | None", ...],
        names: tuple[str, ...],
        prefixes: tuple[str, ...] = (),
        exclude: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self._sources = [s for s in sources if s is not None]
        self._names = names
        self._prefixes = prefixes
        # 에이전트가 어디서도 쓰지 않는 도구(경계의 never). 고른 이름이나 접두어에 걸려도 보이지 않는다
        self._exclude = frozenset(exclude)

    def _picked(self) -> dict[str, JarvisTool]:
        found: dict[str, JarvisTool] = {}
        for name in self._names:
            tool = next((t for s in self._sources if (t := s.get(name)) is not None), None)
            if tool is not None:
                found.setdefault(name, tool)
        if self._prefixes:
            for source in self._sources:
                for tool in source.list_all():
                    if tool.name.startswith(self._prefixes):
                        found.setdefault(tool.name, tool)
        for name, tool in self._tools.items():
            found.setdefault(name, tool)
        return {name: tool for name, tool in found.items() if name not in self._exclude}

    def get(self, name: str) -> JarvisTool | None:
        return self._picked().get(name)

    def list_all(self) -> list[JarvisTool]:
        return list(self._picked().values())
