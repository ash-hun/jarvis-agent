"""task_pattern 기능: KAREN 에게 알려 준 일하는 방식을 KAREN 만 기억하고 새 세션에서 그대로 함을 검증한다."""

import pytest

pytest.importorskip("fastapi")

from tests.fixtures.web_hud_helpers import reply_text, run_turn, scripted_env, use_provider, web_assembly, web_client  # noqa: E402
from tests.fixtures.pattern_provider import ASK_BACK, PatternProvider  # noqa: E402
from tests.fixtures.housing_board import TODAY, Board, page  # noqa: E402
from jarvis.core.tools.housing import housing_tools  # noqa: E402

TEACH = "앞으로 예산이랑 현금 얘기하면 대출은 공고 금액에서 현금을 뺀 걸로, 금리는 4%로 계산해. 기억해."
ASK = "예산 3억, 현금 1억 2천으로 월 200 이하인 공고 추천해줘"
TEXT_KINDS = ("message_update", "stream_delta")


@pytest.fixture
def provider():
    yield from use_provider(PatternProvider())


@pytest.fixture
def client(monkeypatch, tmp_path, provider):
    assembly = web_assembly(monkeypatch, tmp_path, **scripted_env("pattern", tmp_path))
    board = Board(pdf_text=page("rent_terms_uiwang.txt"))
    for tool in housing_tools(board.fetch, lambda: TODAY, board.fetch_file, lambda data: data.decode()):
        assembly.ctx.agent_tools.register_force(tool)
    with web_client(assembly) as test_client:
        yield test_client


def _turns(client, session_id: str, *texts: str) -> list[str]:
    with client.websocket_connect(f"/ws?session_id={session_id}") as ws:
        ws.receive_json()
        return [reply_text(run_turn(ws, text), TEXT_KINDS) for text in texts]


def _karen_session(client) -> str:
    return client.post("/api/sessions", json={"agent": "karen"}).json()["session_id"]


def test_karen_learns_a_pattern_and_uses_it_in_a_new_session(client, provider):
    [saved] = _turns(client, _karen_session(client), TEACH)
    taught_calls = list(provider.calls)
    provider.calls.clear()

    answer, listed = _turns(client, _karen_session(client), ASK, "/patterns")

    assert ("karen", "remember_task_pattern") in taught_calls
    assert "작업 패턴 '예산 기반 공고 추천' 을 karen 의 기억에 저장했다" in saved
    # 새 세션에서도 패턴이 떠올라 되묻지 않고 예산 추천을 바로 했다. 계산 결과가 곧 답이라 모델을 다시 부르지 않는다
    assert provider.calls[:2] == [("karen", "housing_budget")]
    assert ASK_BACK not in answer
    assert "의왕청계2 A1블록" in answer and "월 이자 195,453~219,657원" in answer
    assert "예산 기반 공고 추천" in listed and "대출 = 공고 금액 - 현금" in listed


def test_jarvis_does_not_get_karens_pattern(client, provider):
    _turns(client, _karen_session(client), TEACH)
    provider.saw_pattern.clear()
    provider.calls.clear()

    answer, listed = _turns(client, "default", ASK, "/patterns")

    assert provider.saw_pattern == [("main", False)]
    assert provider.calls == [("main", "ask back")] and ASK_BACK in answer
    assert "저장된 작업 패턴이 없습니다" in listed


def test_without_teaching_karen_still_asks_back(client, provider):
    [answer] = _turns(client, _karen_session(client), ASK)

    assert provider.calls == [("karen", "ask back")] and ASK_BACK in answer
