"""[core] 사용자의 주거 프로필(대출 자격 조건)을 보고, 고치고, 지우는 housing_profile 도구."""

import asyncio
from typing import Any
from datetime import date
from collections.abc import Callable

from jarvis.core.tools.housing.profile import KNOWN, HousingProfile, ProfileStore, apply_updates
from jarvis.model_layer.types import TextContent, ToolResultMessage
from jarvis.core.tools.registry import JarvisTool, ToolContext
from jarvis.core.tools.housing.fetch import kst_today
from jarvis.memory.scope import LOCAL_USER

TOOL_NAME = "housing_profile"
FIELDS = ("homeless", "first_home", "married", "income", "assets", "birth_date", "age", "household", "welfare",
          "student", "regions")

TOOL_DESCRIPTION = (
    "대출과 공공주택 신청 자격을 가르는 사용자의 주거 프로필(무주택, 생애최초, 혼인, 연소득, 순자산,"
    " 생년월일이나 나이, 가구원수, 기초생활 수급자, 대학생, 관심 지역)을"
    " 보거나 고친다. 사용자가 자기 조건을 말하거나 바뀌었다고 하면('연소득이 7천으로 올랐어', '결혼했어')"
    " action=set 으로 그 항목만 넣는다."
    " 준 항목만 바뀌고 나머지는 그대로다. housing_budget 은 저장된 프로필로 자격을 가린다."
    " '앞으로 서울, 경기만 찾아' 처럼 찾을 지역을 정하면 regions 에 넣는다."
    " 공고 도구들이 지역을 받지 않으면 이 지역으로 찾는다."
)
TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["get", "set", "clear"], "description": "get 보기, set 고치기, clear"},
        "homeless": {"type": "boolean", "description": "세대원 전원 무주택인가"},
        "first_home": {"type": "boolean", "description": "생애최초 혜택을 아직 쓰지 않았는가"},
        "married": {"type": "boolean", "description": "기혼인가"},
        "income": {"type": "string", "description": "연소득(미혼은 본인, 기혼은 부부 합산). 예: 6000만"},
        "assets": {"type": "string", "description": "순자산. 예: 2억"},
        "birth_date": {"type": "string", "description": "생년월일 YYYY-MM-DD. 사용자가 말했을 때만"},
        "age": {"type": "integer", "description": "만 나이. 생년월일을 모를 때만"},
        "household": {"type": "integer", "description": "본인을 넣은 세대 구성원 수"},
        "welfare": {"type": "boolean", "description": "기초생활 수급자(생계, 의료, 주거급여)인가"},
        "student": {"type": "boolean", "description": "대학생(재학, 휴학)인가"},
        "regions": {"type": "string", "description": "관심 지역(시도). 쉼표로 여럿. 예: 서울,경기. 지우려면 비움"},
    },
    "required": ["action"],
}


def describe(profile: HousingProfile, today: date) -> str:
    if profile.is_empty():
        return "저장된 주거 프로필이 없다. 모르는 조건은 상품마다 자격 확인으로 남는다."
    return "주거 프로필:\n" + "\n".join(f"- {line}" for line in profile.lines(today))


class HousingProfileTool(JarvisTool):
    """사용자마다 한 항목이다. 같은 값으로 다시 set 해도 결과가 같다."""

    name = TOOL_NAME
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS
    execution_mode = "sequential"

    def __init__(self, store: ProfileStore, today: Callable[[], date] = kst_today) -> None:
        self._store = store
        self._today = today

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
        context: ToolContext | None = None,
    ) -> ToolResultMessage:
        scope = getattr(context, "scope", None)
        if scope is None:
            return _result(tool_call_id, "부른 세션의 범위가 없어 프로필을 다루지 않았다", True)
        user = scope.user_id or LOCAL_USER
        today = self._today()
        action = str(params.get("action") or "get")
        if action == "clear":
            removed = await self._store.clear(user)
            return _result(tool_call_id, "주거 프로필을 지웠다." if removed else "지울 주거 프로필이 없다.")
        current = await self._store.get(user)
        if action == "get":
            return _result(tool_call_id, describe(current, today))
        updates = {k: params[k] for k in FIELDS if params.get(k) not in (None, "")}
        if not updates:
            return _result(tool_call_id, f"고칠 항목이 없다. 쓸 수 있는 것: {KNOWN}", True)
        try:
            updated = apply_updates(current, updates, today)
        except ValueError as exc:
            return _result(tool_call_id, f"고칠 수 없다: {exc}", True)
        await self._store.save(updated, scope, today)
        return _result(tool_call_id, "저장했다. " + describe(updated, today))


def _result(tool_call_id: str, text: str, is_error: bool = False) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id, tool_name=TOOL_NAME, content=[TextContent(text=text)], is_error=is_error
    )
