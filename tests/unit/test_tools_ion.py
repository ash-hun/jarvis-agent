"""tools 의 Ion 도구 넷: 상태와 사고를 글로 옮기고, 답과 재기동을 보내며, Ion 이 없으면 오류 결과를 돌려준다."""

import json
import httpx

from jarvis.core.tools.ion.ion_tools import (
    IonIncidentsTool, IonReportTool, IonRespondTool, IonStatusTool, resolve_incident,
)
from jarvis.core.tools.ion.ion_format import LOG_NOTICE, fmt_ms, status_text
from jarvis.core.tools.ion.ion_client import IonClient
from tests.fixtures.tools_helpers import route_httpx

OPEN = {"id": "backend_down:backend:1000", "kind": "backend_down", "target": "backend",
        "detail": "health 실패 3회 연속", "title": "Ion: 백엔드가 응답하지 않아요", "opened_ms": 1000,
        "response": None, "closed_ms": None}
CLOSED = {**OPEN, "id": "backend_down:backend:5", "opened_ms": 5, "response": "restart", "responded_ms": 6,
          "action_result": "재기동함", "closed_ms": 9}
STATUS = {"backend_ok": True, "observed_ms": 2000, "loop_lag_ms": 7.5,
          "container": {"service": "jarvis-backend", "status": "running", "restart_count": 1,
                        "memory_usage": 1_048_576 * 100, "memory_limit": 1_048_576 * 1000},
          "agents": {"karen": {"fail_streak": 0, "last_ok_ms": 1500, "scheduled": True, "last_active_ms": 1600}},
          "incidents": [OPEN]}


def _handler(seen: list[tuple[str, str, dict]], down: bool = False):  # type: ignore[no-untyped-def]
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        seen.append((request.method, request.url.path, {**dict(request.url.params), **body}))
        if down:
            raise httpx.ConnectError("down")
        if request.url.path == "/ion/status":
            return httpx.Response(200, json=STATUS)
        if request.url.path == "/ion/incidents":
            return httpx.Response(200, json={"incidents": [OPEN, CLOSED]})
        if request.url.path == "/ion/restart":
            return httpx.Response(200, json={"ok": True, "result": "재기동함"})
        if request.url.path.endswith("/respond"):
            if "ghost" in request.url.path:
                return httpx.Response(404, json={"error": "unknown incident"})
            incident = {**OPEN, "response": body["action"], "action_result": "재기동함"}
            return httpx.Response(200, json={"incident": incident})
        if request.url.path == "/ion/logs":
            return httpx.Response(200, json={"text": "line1\nline2", "lines": 2})
        return httpx.Response(404)

    return handle


def _client(monkeypatch, down: bool = False):  # type: ignore[no-untyped-def]
    seen: list[tuple[str, str, dict]] = []
    route_httpx(monkeypatch, _handler(seen, down))
    return IonClient("http://ion", "k"), seen


async def test_status_tool_renders_backend_container_agents_and_open_incidents(monkeypatch):
    client, _ = _client(monkeypatch)
    text = (await IonStatusTool(client).execute("c1", {})).content[0].text
    assert "백엔드 응답: 정상" in text and "재시작 1회" in text and "메모리 10% (100MB / 1000MB)" in text
    assert "이벤트 루프 지연: 8ms" in text and "에이전트 karen: 연속 실패 0회" in text
    assert "열린 사고 1건:" in text and "[backend_down:backend:1000]" in text and fmt_ms(1000) in text


def test_status_text_marks_unobserved_values():
    text = status_text({"backend_ok": None, "agents": {}, "incidents": []})
    assert "미관측" in text and "이벤트 루프 지연: -" in text and "열린 사고 0건" in text


async def test_incidents_tool_lists_open_and_closed_with_responses(monkeypatch):
    client, seen = _client(monkeypatch)
    text = (await IonIncidentsTool(client).execute("c1", {"limit": 5})).content[0].text
    assert seen[0][2] == {"closed": "1", "limit": "5"}
    assert "열려 있음" in text and "답 restart" in text and "결과 재기동함" in text and f"닫힘 {fmt_ms(9)}" in text


async def test_respond_tool_answers_an_incident_or_restarts_without_one(monkeypatch):
    client, seen = _client(monkeypatch)
    tool = IonRespondTool(client)
    answered = await tool.execute("c1", {"action": "restart", "incident_id": "backend_down:backend:1000"})
    assert answered.is_error is False and "restart 로 답함" in answered.content[0].text
    assert seen[-1][:2] == ("POST", "/ion/incidents/backend_down:backend:1000/respond")

    restarted = await tool.execute("c2", {"action": "restart"})
    assert restarted.is_error is False and seen[-1][:2] == ("POST", "/ion/restart")

    assert (await tool.execute("c3", {"action": "pause"})).is_error is True
    assert (await tool.execute("c4", {"action": "dance"})).is_error is True
    assert "모르는 사고" in (await tool.execute("c5", {"action": "ignore", "incident_id": "ghost"})).content[0].text


async def test_report_tool_fetches_logs_around_the_incident_and_marks_them_untrusted(monkeypatch):
    client, seen = _client(monkeypatch)
    result = await IonReportTool(client).execute("c1", {"incident_id": "backend_down:backend:5", "lines": 50})
    text = result.content[0].text
    assert LOG_NOTICE in text and "line1\nline2" in text and "답 restart" in text
    # 열린 시각 5ms 에서 10분을 빼면 0 이하라 since 를 보내지 않고, 닫힌 시각까지 본다
    assert seen[-1][:2] == ("GET", "/ion/logs") and seen[-1][2] == {"lines": "50", "until_ms": "9"}
    assert "모르는 사고" in (await IonReportTool(client).execute("c2", {"incident_id": "nope"})).content[0].text


async def test_tools_return_an_error_result_when_ion_is_unreachable(monkeypatch):
    client, _ = _client(monkeypatch, down=True)
    for tool in (IonStatusTool(client), IonIncidentsTool(client), IonReportTool(client)):
        result = await tool.execute("c1", {"incident_id": "x"})
        assert result.is_error is True and "닿지 않는다" in result.content[0].text


def test_resolve_incident_accepts_the_exact_id_or_a_unique_numeric_tail():
    rows = [{"id": "backend_down:backend:1000"}, {"id": "agent_failing:karen:1000"}, {"id": "backend_down:backend:5"}]
    assert resolve_incident(rows, "backend_down:backend:5") == rows[2]
    assert resolve_incident(rows, "5") == rows[2]
    assert resolve_incident(rows, "1000") is None and resolve_incident(rows, "ghost") is None


async def test_report_and_respond_take_the_numeric_tail_the_model_tends_to_send(monkeypatch):
    client, seen = _client(monkeypatch)
    report = await IonReportTool(client).execute("c1", {"incident_id": "5"})
    assert report.is_error is False and "답 restart" in report.content[0].text
    answered = await IonRespondTool(client).execute("c2", {"action": "ignore", "incident_id": "1000"})
    assert answered.is_error is False and seen[-1][1] == "/ion/incidents/backend_down:backend:1000/respond"
