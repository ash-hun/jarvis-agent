"""KAREN 에게 알려 준 일하는 방식을 KAREN 만 기억하고, 새 세션의 같은 종류 요청에서 되묻지 않고 그대로 한다."""

import pytest
from pathlib import Path

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from tests.fixtures.pattern_provider import ASK_BACK, PatternProvider  # noqa: E402
from tests.unit.core.housing.conftest import TODAY, page  # noqa: E402
from tests.unit.core.housing.test_budget import Board  # noqa: E402
from jarvis.core.tools.housing import housing_tools  # noqa: E402
from jarvis.jarvis_config import JarvisSettings  # noqa: E402
from jarvis.app.infra_builder import build_app  # noqa: E402
from jarvis.ui.web.server import create_app  # noqa: E402

TEAM_DIR = Path(__file__).resolve().parents[2] / "team"
TEACH = "앞으로 예산이랑 현금 얘기하면 대출은 공고 금액에서 현금을 뺀 걸로, 금리는 4%로 계산해. 기억해."
ASK = "예산 3억, 현금 1억 2천으로 월 200 이하인 공고 추천해줘"


@pytest.fixture
def provider():
    from jarvis.model_layer.model_registry import get_default_registry

    scripted = PatternProvider()
    registry = get_default_registry()
    registry._providers["pattern"] = scripted
    yield scripted
    registry._providers.pop("pattern", None)


@pytest.fixture
def client(monkeypatch, tmp_path, provider):
    for key, value in {
        "JARVIS_TEAM__DIR": str(TEAM_DIR),
        "JARVIS_LLM__PROVIDER": "pattern",
        "JARVIS_LLM__MODEL": "pattern-1",
        "JARVIS_THOUGHT__ENABLED": "false",
        "JARVIS_PROACTIVE__DAEMON_ENABLED": "false",
        "JARVIS_SCHEDULER__ENABLED": "false",
        "JARVIS_MEMORY__BACKEND": "in_memory",
        "JARVIS_SESSION__PERSISTENCE_BACKEND": "jsonl",
        "JARVIS_SESSION__SESSIONS_DIR": str(tmp_path / "sessions"),
        "JARVIS_SECURITY__AGENT_APPROVALS_DIR": str(tmp_path / "approvals"),
    }.items():
        monkeypatch.setenv(key, value)
    assembly = build_app(JarvisSettings())
    board = Board(pdf_text=page("rent_terms_uiwang.txt"))
    for tool in housing_tools(board.fetch, lambda: TODAY, board.fetch_file, lambda data: data.decode()):
        assembly.ctx.agent_tools.register_force(tool)
    with TestClient(create_app(assembly, initial_session_id="default")) as test_client:
        yield test_client


def _turn(ws, text):
    import time

    seen = []
    ws.send_json({"type": "user_message", "text": text})
    while True:
        msg = ws.receive_json()
        seen.append(msg)
        if msg["type"] == "agent_end":
            return seen
        if msg["type"] == "error" and "처리 중" in msg["message"]:
            time.sleep(0.1)
            ws.send_json({"type": "user_message", "text": text})


def _text(seen) -> str:
    kinds = ("message_update", "stream_delta")
    return "".join(m.get("text_delta", "") or m.get("text", "") for m in seen if m["type"] in kinds)


def _karen_session(client) -> str:
    return client.post("/api/sessions", json={"agent": "karen"}).json()["session_id"]


def test_karen_learns_a_pattern_and_uses_it_in_a_new_session(client, provider):
    with client.websocket_connect(f"/ws?session_id={_karen_session(client)}") as ws:
        ws.receive_json()
        saved = _text(_turn(ws, TEACH))
    assert ("karen", "remember_task_pattern") in provider.calls
    assert "작업 패턴 '예산 기반 공고 추천' 을 karen 의 기억에 저장했다" in saved

    provider.calls.clear()
    with client.websocket_connect(f"/ws?session_id={_karen_session(client)}") as ws:
        ws.receive_json()
        answer = _text(_turn(ws, ASK))
        listed = _text(_turn(ws, "/patterns"))
    # 새 세션에서도 패턴이 떠올라 되묻지 않고 예산 추천을 바로 했다. 계산 결과가 곧 답이라 모델을 다시 부르지 않는다
    assert provider.calls[:2] == [("karen", "housing_budget")]
    assert ASK_BACK not in answer
    assert "의왕청계2 A1블록" in answer and "월 이자 195,453~219,657원" in answer
    assert "예산 기반 공고 추천" in listed and "대출 = 공고 금액 - 현금" in listed


def test_jarvis_does_not_get_karens_pattern(client, provider):
    with client.websocket_connect(f"/ws?session_id={_karen_session(client)}") as ws:
        ws.receive_json()
        _turn(ws, TEACH)
    provider.saw_pattern.clear()
    provider.calls.clear()
    with client.websocket_connect("/ws?session_id=default") as ws:
        ws.receive_json()
        answer = _text(_turn(ws, ASK))
        listed = _text(_turn(ws, "/patterns"))
    assert provider.saw_pattern == [("main", False)]
    assert provider.calls == [("main", "ask back")] and ASK_BACK in answer
    assert "저장된 작업 패턴이 없습니다" in listed


def test_without_teaching_karen_still_asks_back(client, provider):
    with client.websocket_connect(f"/ws?session_id={_karen_session(client)}") as ws:
        ws.receive_json()
        answer = _text(_turn(ws, ASK))
    assert provider.calls == [("karen", "ask back")] and ASK_BACK in answer
