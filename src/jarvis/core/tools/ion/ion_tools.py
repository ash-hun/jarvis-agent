"""[agent] Ion 프로필의 도구 넷: 플랫폼 상태, 사고 목록, 사고 답하기(또는 재기동), 사고 보고서 재료."""

from typing import Any

from jarvis.core.tools.ion.ion_format import incidents_text, report_text, status_text
from jarvis.model_layer.model_types import TextContent, ToolResultMessage
from jarvis.core.tools.ion.ion_client import IonClient, IonUnavailable
from jarvis.core.tools.tools_registry import JarvisTool

ACTIONS = ("restart", "stop", "pause", "ignore")
DEFAULT_LIMIT = 20
DEFAULT_LOG_LINES = 200
MAX_LOG_LINES = 500
# 사고가 열리기 얼마 전부터 로그를 본다. 원인은 보통 사고 직전에 찍힌다
REPORT_BEFORE_MS = 10 * 60_000


def resolve_incident(incidents: list[dict[str, Any]], given: str) -> dict[str, Any] | None:
    """사고 id 를 찾는다. 모델이 숫자만 옮길 때가 있어(실측) 끝이 맞는 유일한 사고도 받는다. 순수 함수."""
    exact = [i for i in incidents if i.get("id") == given]
    if exact:
        return exact[0]
    tail = [i for i in incidents if str(i.get("id", "")).endswith(f":{given}")]
    return tail[0] if len(tail) == 1 else None


def _result(tool_call_id: str, text: str, error: bool = False) -> ToolResultMessage:
    return ToolResultMessage(tool_call_id=tool_call_id, tool_name="", content=[TextContent(text=text)], is_error=error)


class IonStatusTool(JarvisTool):
    name = "ion_status"
    description = (
        "플랫폼(백엔드 컨테이너와 에이전트들)의 지금 상태. 백엔드 응답 여부, 컨테이너 상태와 재시작 수, 메모리,"
        " 이벤트 루프 지연, 에이전트별 연속 실패와 마지막 성공, 열린 사고. '지금 뭐가 아파?', '괜찮아?' 에 먼저 부른다."
    )
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    def __init__(self, client: IonClient) -> None:
        self._client = client

    async def execute(self, tool_call_id: str, params: dict[str, Any], signal: Any = None) -> ToolResultMessage:
        try:
            return _result(tool_call_id, status_text(await self._client.status()))
        except IonUnavailable as exc:
            return _result(tool_call_id, str(exc), True)


class IonIncidentsTool(JarvisTool):
    name = "ion_incidents"
    description = (
        "사고 기록. 열린 사고와 최근 닫힌 사고를 최신순으로. '어제 무슨 일 있었어?', '최근 사고 알려줘' 에 쓴다."
        " 사고 id 는 ion_respond, ion_report 에 넣는다."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "closed": {"type": "boolean", "description": "닫힌 사고도 볼지. 기본 true"},
            "limit": {"type": "integer", "description": f"최대 건수. 기본 {DEFAULT_LIMIT}"},
        },
    }

    def __init__(self, client: IonClient) -> None:
        self._client = client

    async def execute(self, tool_call_id: str, params: dict[str, Any], signal: Any = None) -> ToolResultMessage:
        closed = bool(params.get("closed", True))
        limit = max(1, min(int(params.get("limit") or DEFAULT_LIMIT), 100))
        try:
            return _result(tool_call_id, incidents_text(await self._client.incidents(closed, limit)))
        except IonUnavailable as exc:
            return _result(tool_call_id, str(exc), True)


class IonRespondTool(JarvisTool):
    name = "ion_respond"
    description = (
        "사고에 답하거나 백엔드를 재기동한다. incident_id 가 있으면 그 사고의 버튼(restart, stop, pause, ignore)을"
        " 대신 누른다. incident_id 없이 action=restart 면 사고와 무관하게 백엔드를 재기동한다."
        " 사용자가 분명히 시켰을 때만 부른다('응 재시작해', '그 사고는 무시해')."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "incident_id": {"type": "string", "description": "ion_incidents 나 ion_status 의 사고 id. 비우면 재기동만"},
        },
        "required": ["action"],
    }

    def __init__(self, client: IonClient) -> None:
        self._client = client

    async def execute(self, tool_call_id: str, params: dict[str, Any], signal: Any = None) -> ToolResultMessage:
        action = str(params.get("action") or "")
        incident_id = str(params.get("incident_id") or "").strip()
        if action not in ACTIONS:
            return _result(tool_call_id, f"action 은 {', '.join(ACTIONS)} 중 하나", True)
        try:
            if not incident_id:
                if action != "restart":
                    return _result(tool_call_id, "사고 id 없이 할 수 있는 것은 restart 뿐이다", True)
                ok = await self._client.restart()
                return _result(tool_call_id, "백엔드를 재기동했다" if ok else "재기동 실패", not ok)
            found = resolve_incident(await self._client.incidents(True, 100), incident_id)
            incident = await self._client.respond(str(found["id"]), action) if found is not None else None
        except IonUnavailable as exc:
            return _result(tool_call_id, str(exc), True)
        if incident is None:
            return _result(tool_call_id, f"모르는 사고 id: {incident_id}", True)
        incident_id = str(incident.get("id") or incident_id)
        response, outcome = incident.get("response"), incident.get("action_result")
        return _result(tool_call_id, f"사고 {incident_id} 에 {response} 로 답함. 결과: {outcome}")


class IonReportTool(JarvisTool):
    name = "ion_report"
    description = (
        "사고 보고서 재료. 사고 타임라인과 그 전후(열리기 10분 전부터 닫힐 때까지)의 백엔드 로그를 돌려준다."
        " '왜 죽었어?', '보고서 써 줘' 에 쓴다. 로그를 읽고 원인과 경과를 짧게 정리해 답한다."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "incident_id": {"type": "string"},
            "lines": {"type": "integer", "description": f"로그 줄 수. 기본 {DEFAULT_LOG_LINES}, 최대 {MAX_LOG_LINES}"},
        },
        "required": ["incident_id"],
    }

    def __init__(self, client: IonClient, now_ms: Any = None) -> None:
        self._client = client
        self._now_ms = now_ms

    async def execute(self, tool_call_id: str, params: dict[str, Any], signal: Any = None) -> ToolResultMessage:
        incident_id = str(params.get("incident_id") or "").strip()
        lines = max(10, min(int(params.get("lines") or DEFAULT_LOG_LINES), MAX_LOG_LINES))
        if not incident_id:
            return _result(tool_call_id, "incident_id 가 필요하다", True)
        try:
            incident = resolve_incident(await self._client.incidents(True, 100), incident_id)
            if incident is None:
                return _result(tool_call_id, f"모르는 사고 id: {incident_id}", True)
            since = int(incident.get("opened_ms") or 0) - REPORT_BEFORE_MS
            until = incident.get("closed_ms")
            logs = await self._client.logs(since if since > 0 else None, int(until) if until else None, lines)
        except IonUnavailable as exc:
            return _result(tool_call_id, str(exc), True)
        return _result(tool_call_id, report_text(incident, logs))


def ion_tools(client: IonClient) -> list[JarvisTool]:
    return [IonStatusTool(client), IonIncidentsTool(client), IonRespondTool(client), IonReportTool(client)]
