"""[core] 사용자가 알려 준 작업 방식을 부른 에이전트의 작업 패턴 기억으로 저장하는 remember_task_pattern 도구."""

import asyncio
from typing import TYPE_CHECKING, Any

from jarvis.memory.long_term.task_pattern import TaskPattern, normalize_keywords
from jarvis.model_layer.types import TextContent, ToolResultMessage
from jarvis.core.tools.registry import JarvisTool, ToolContext
from jarvis.memory.scope import current_scope

if TYPE_CHECKING:
    from jarvis.memory.memory_service import MemoryService

TASK_PATTERN_TOOL = "remember_task_pattern"

TOOL_DESCRIPTION = (
    "사용자가 어떤 작업을 어떻게 할지 설명하거나 '앞으로 이렇게 해', '기억해' 라고 하면"
    " 그 방식을 이 에이전트의 작업 패턴으로 저장한다."
    " 다음에 키워드가 든 요청이 오면 저장한 방식이 기억으로 들어온다. 같은 이름으로 다시 저장하면 고친다."
    " 말로만 기억하겠다고 하지 말고 이 도구를 부른다. 사용자에 대한 사실(이름, 취향)은 여기에 저장하지 않는다."
)
TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "짧은 이름. 예: 예산 기반 공고 추천"},
        "when": {"type": "string", "description": "어떤 요청일 때 쓰는지. 예: 총예산과 현금으로 공고 추천 요청"},
        "steps": {"type": "string", "description": "어떻게 하는지. 단계, 계산식, 기본값. 예: 대출 = 총예산 - 현금"},
        "keywords": {"type": "string", "description": "요청에 들어갈 말, 쉼표로. 예: 예산, 현금, 월 상환, 추천"},
    },
    "required": ["name", "when", "steps", "keywords"],
}


class TaskPatternTool(JarvisTool):
    """부른 세션의 에이전트 범위로 저장한다. JARVIS 와 KAREN 이 같은 이름으로 저장해도 서로 다른 항목이다."""

    name = TASK_PATTERN_TOOL
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS
    execution_mode = "sequential"

    def __init__(self, memory: "MemoryService") -> None:
        self._memory = memory

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
        context: ToolContext | None = None,
    ) -> ToolResultMessage:
        name = str(params.get("name") or "").strip()
        when = str(params.get("when") or "").strip()
        steps = str(params.get("steps") or "").strip()
        keywords = normalize_keywords(params.get("keywords") or "")
        if not (name and when and steps and keywords):
            return _result(tool_call_id, "name, when, steps, keywords(두 글자 이상 하나 이상)가 모두 필요하다", True)
        scope = getattr(context, "scope", None) or current_scope.get()
        await self._memory.remember_pattern(TaskPattern(name, when, steps, keywords), scope=scope)
        agent = scope.agent_id if scope is not None else "main"
        return _result(
            tool_call_id,
            f"작업 패턴 '{name}' 을 {agent} 의 기억에 저장했다(같은 이름이면 고쳐 썼다)."
            f" 다음에 요청에 {', '.join(keywords)} 중 하나가 들어 있으면 이 방식이 떠오른다.",
        )


def _result(tool_call_id: str, text: str, is_error: bool = False) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id, tool_name=TASK_PATTERN_TOOL, content=[TextContent(text=text)], is_error=is_error
    )
