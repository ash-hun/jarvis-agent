"""[core] 대화 중에 "1분 뒤에 알려줘" 같은 요청을 /schedule 과 같은 규칙으로 스케줄러에 등록하는 schedule 도구."""

import asyncio
from typing import TYPE_CHECKING, Any

from jarvis.model_layer.types import TextContent, ToolResultMessage
from jarvis.core.tools.registry import JarvisTool, ToolContext

if TYPE_CHECKING:
    from jarvis.core.slash.dispatcher import ScopedHandler

SCHEDULE_TOOL = "schedule"
# /schedule 핸들러가 등록에 성공했을 때만 이 말로 시작한다
REGISTERED_PREFIXES = ("[Schedule] 한 번 실행 등록 완료", "[Schedule] 작업 등록 완료")

TOOL_DESCRIPTION = (
    "사용자가 정한 시각에 알림을 받거나 일을 시키려 하면('1분 뒤에 알려줘', '오후 7시에 회의 준비 알려줘',"
    " '내일 9시에 뉴스 요약해줘') 이 도구로 등록한다. 등록하면 그 시각에 앱 푸시와 화면으로 알림이 간다."
    " 말로만 알려 드리겠다고 하지 말고 반드시 이 도구를 부른다. 등록 결과의 시각을 그대로 사용자에게 말한다."
)
TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "request": {
            "type": "string",
            "description": (
                "'<시각>에 <내용>' 꼴. 시각은 'N분 뒤에', 'N시간 뒤에', '오후 7시에', '내일 09:30에',"
                " '2026.10.01 오후 7시에' 중 하나. 마감까지 반복이면 '2026.06.01 오전 9시까지 <내용>'."
                " 예: '1분 뒤에 푸시 테스트'"
            ),
        },
    },
    "required": ["request"],
}


class ScheduleTool(JarvisTool):
    """# idempotent: 같은 요청을 두 번 부르면 알림도 두 개다, 사용자가 같은 말을 두 번 하면 두 번 원한 것으로 본다

    /schedule 과 같은 핸들러를 쓴다. 일정은 부른 세션의 에이전트가 맡는다.
    """

    name = SCHEDULE_TOOL
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS
    execution_mode = "sequential"

    def __init__(self, handler: "ScopedHandler") -> None:
        self._handler = handler

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
        context: ToolContext | None = None,
    ) -> ToolResultMessage:
        request = str(params.get("request") or "").strip()
        scope = getattr(context, "scope", None)
        if not request or scope is None:
            return _result(tool_call_id, "request 와 부른 세션의 범위가 필요하다. 등록하지 않았다", True)
        text = await self._handler(request, scope)
        return _result(tool_call_id, text, not text.startswith(REGISTERED_PREFIXES))


def _result(tool_call_id: str, text: str, is_error: bool = False) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id, tool_name=SCHEDULE_TOOL, content=[TextContent(text=text)], is_error=is_error
    )
