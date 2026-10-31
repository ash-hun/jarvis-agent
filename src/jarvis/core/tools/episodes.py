"""[core] 부른 에이전트의 지난 턴 일화(EDM)를 작업 종류, 성패, 기간으로 골라 회상하는 recall_episodes 도구."""

import asyncio
from typing import TYPE_CHECKING, Any
from datetime import date, datetime, timedelta

from jarvis.model_layer.types import TextContent, ToolResultMessage
from jarvis.core.tools.registry import JarvisTool, ToolContext

if TYPE_CHECKING:
    from jarvis.memory.memory_service import MemoryService

RECALL_EPISODES_TOOL = "recall_episodes"
DEFAULT_LIMIT = 5
MAX_LIMIT = 10

TOOL_DESCRIPTION = (
    "이 에이전트가 지난 대화에서 한 일을 골라 떠올린다. 최근 3턴보다 앞의 대화는 모델에 들어 있지 않으므로,"
    " '지난번 그 계산', '저번 주에 실패한 거' 처럼 예전 작업을 물으면 이 도구로 찾는다."
    " task_type 은 그 턴에서 처음 부른 도구 이름이고 도구를 안 쓴 대화는 chat 이다."
)
TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "찾을 내용의 낱말. 예: 대출 계산"},
        "task_type": {"type": "string", "description": "도구 이름 또는 chat. 비우면 전부"},
        "outcome": {"type": "string", "enum": ["success", "failure"], "description": "비우면 전부"},
        "since": {"type": "string", "description": "YYYY-MM-DD, 이날 포함"},
        "until": {"type": "string", "description": "YYYY-MM-DD, 이날 포함"},
        "limit": {"type": "integer", "description": f"최대 {MAX_LIMIT}, 기본 {DEFAULT_LIMIT}"},
    },
    "required": ["query"],
}


class RecallEpisodesTool(JarvisTool):
    """읽기만 한다. 부른 세션의 범위와 그 에이전트의 읽기 정책 안에서만 찾는다."""

    name = RECALL_EPISODES_TOOL
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS
    execution_mode = "parallel"

    def __init__(self, memory: "MemoryService") -> None:
        self._memory = memory

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
        context: ToolContext | None = None,
    ) -> ToolResultMessage:
        query = str(params.get("query") or "").strip()
        scope = getattr(context, "scope", None)
        if not query:
            return _result(tool_call_id, "query 가 필요하다", True)
        if scope is None:
            return _result(tool_call_id, "부른 세션의 범위가 없어 찾지 않았다", True)
        try:
            since = _day(params.get("since"))
            until = _day(params.get("until"))
        except ValueError:
            return _result(tool_call_id, "since, until 은 YYYY-MM-DD 여야 한다", True)
        outcome = params.get("outcome") or None
        if outcome not in (None, "success", "failure"):
            return _result(tool_call_id, "outcome 은 success 또는 failure 다", True)
        limit = min(MAX_LIMIT, max(1, int(params.get("limit") or DEFAULT_LIMIT)))
        items = await self._memory.recall_episodes(
            query, scope, task_type=params.get("task_type") or None, outcome=outcome, since=since,
            until=until + timedelta(days=1) if until else None, limit=limit,
        )
        if not items:
            return _result(tool_call_id, "조건에 맞는 지난 일화가 없다")
        lines = [f"- [{(i.occurred_at or i.created_at):%Y-%m-%d}] {i.content}" for i in items]
        return _result(tool_call_id, "\n".join(lines))


def _day(value: Any) -> datetime | None:
    if not value:
        return None
    d = date.fromisoformat(str(value))
    return datetime(d.year, d.month, d.day)


def _result(tool_call_id: str, text: str, is_error: bool = False) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id, tool_name=RECALL_EPISODES_TOOL, content=[TextContent(text=text)], is_error=is_error
    )
