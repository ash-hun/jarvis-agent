"""housing 기능: KAREN 이 LH, SH 청약 공고를 찾고 대출을 계산하며, 게시판 오류는 지어내지 않고 알림을 검증한다."""

import pytest

pytest.importorskip("fastapi")

from tests.fixtures.web_hud_helpers import reply_text, run_turn, scripted_env, use_provider, web_assembly, web_client  # noqa: E402
from tests.fixtures.housing_board import TODAY, FakeBoard, page  # noqa: E402
from tests.fixtures.housing_provider import HousingProvider  # noqa: E402
from jarvis.core.tools.housing import housing_tools  # noqa: E402

HOUSING_TOOLS = {"lh_notice", "sh_notice", "housing_loan"}


@pytest.fixture
def provider():
    yield from use_provider(HousingProvider())


@pytest.fixture
def board():
    return FakeBoard({
        "selectWrtancList.do": page("lh_list.html"),
        "selectWrtancInfo.do": page("lh_detail_sale.html"),
        "list.do": page("sh_list.html"),
        "view.do": page("sh_detail.html"),
    })


def _assembly(monkeypatch, tmp_path, board):
    """저장소의 team/karen.yaml 을 그대로 쓰고 게시판과 오늘 날짜만 바꾼다."""
    assembly = web_assembly(monkeypatch, tmp_path, **scripted_env("housing", tmp_path))
    # 세션은 아직 열리지 않아 첫 세션부터 이 도구를 쓴다
    for tool in housing_tools(board, lambda: TODAY):
        assembly.ctx.agent_tools.register_force(tool)
    return assembly


def test_jarvis_asks_karen_for_newlywed_notice_and_loan(monkeypatch, tmp_path, provider, board):
    """사용자가 JARVIS 에게 묻고, KAREN 이 LH 목록, 상세, 대출 계산을 차례로 해 답한다."""
    with web_client(_assembly(monkeypatch, tmp_path, board)) as client:
        with client.websocket_connect("/ws?session_id=default") as ws:
            ws.receive_json()
            seen = run_turn(ws, "신혼희망타운 공고중인 거 찾아서 분양가로 대출 상환액도 알려줘")
            # 앱을 닫을 때 세션 요약도 같은 프로바이더를 부르므로 턴이 끝난 시점의 호출만 본다
            calls = list(provider.calls)

    assert [(who, tool) for who, tool, _ in calls] == [
        ("main", "ask_agent"),
        ("karen", "lh_notice"),
        ("karen", "lh_notice"),
        ("karen", "housing_loan"),
        ("karen", "say"),
        ("main", "say"),
    ]
    # 상세는 목록에서 고른 공공분양 공고, 대출은 그 공고 id 와 상세에서 본 주택형
    assert calls[2][2] == {"id": "0000061179-02-39-39"}
    assert (calls[3][2]["notice_id"], calls[3][2]["unit"]) == ("0000061179-02-39-39", "55A")
    # 게시판에는 신혼희망타운 분류의 공고중 목록, 그다음 그 공고 상세를 물었다. housing_loan 도 상세를 한 번 더 읽는다
    (list_url, form), (detail_url, detail), (loan_url, _) = board.calls
    assert loan_url == detail_url
    assert list_url.endswith("selectWrtancList.do")
    assert (form["mi"], form["srchUppAisTpCd"], form["panSs"]) == ("1026", "39", "공고중")
    assert detail_url.endswith("selectWrtancInfo.do") and detail["panId"] == "0000061179"
    final = reply_text(seen)
    assert "K.A.R.E.N. 의 답" in final
    assert "인천계양 A17블록 신혼희망타운(공공분양) 입주자모집공고 (D-14)" in final
    assert "55.9000A 평균분양가격(원) 504,484,000원" in final
    assert "대출원금 353,138,800원" in final and "월 상환액 1,585,751원" in final


def test_karen_session_reads_sh_notice_with_tools_only_karen_has(monkeypatch, tmp_path, provider, board):
    """KAREN 세션에서 바로 SH 행복주택 공고를 찾고 첫 글의 첨부까지 본다. 청약 도구는 KAREN 에게만 있다."""
    with web_client(_assembly(monkeypatch, tmp_path, board)) as client:
        sid = client.post("/api/sessions", json={"agent": "karen"}).json()["session_id"]
        with client.websocket_connect(f"/ws?session_id={sid}") as ws:
            hello = ws.receive_json()
            seen = run_turn(ws, "SH 행복주택 공고 보여줘")
            calls = list(provider.calls)
        with client.websocket_connect("/ws?session_id=default") as ws:
            ws.receive_json()
        karen = {t["name"] for t in client.get(f"/api/tools?session_id={sid}").json()["tools"]}
        jarvis = {t["name"] for t in client.get("/api/tools?session_id=default").json()["tools"]}

    assert hello["agent"]["id"] == "karen"
    assert [(who, tool) for who, tool, _ in calls] == [("karen", "sh_notice"), ("karen", "sh_notice"), ("karen", "say")]
    assert calls[1][2] == {"seq": "310563"}
    assert board.calls[0][1]["srchTp"] == "0"
    final = reply_text(seen)
    assert "SH 공고 상세: 2026년 2차 행복주택 서류심사 대상자 발표 및 서류 제출 안내" in final
    assert "(0) 행복주택 심사 서류 제출 안내문.pdf" in final and "htmlConverter.do" in final
    assert karen >= HOUSING_TOOLS
    assert not HOUSING_TOOLS & jarvis


def test_board_down_is_reported_not_invented(monkeypatch, tmp_path, provider):
    """게시판이 오류면 KAREN 은 도구 오류를 그대로 알린다. 지어낸 공고가 나오지 않는다."""
    with web_client(_assembly(monkeypatch, tmp_path, FakeBoard({}))) as client:
        sid = client.post("/api/sessions", json={"agent": "karen"}).json()["session_id"]
        with client.websocket_connect(f"/ws?session_id={sid}") as ws:
            ws.receive_json()
            final = reply_text(run_turn(ws, "신혼희망타운 공고 찾아줘"))

    assert "조회하지 못했습니다. LH 게시판 조회 실패" in final
    assert "D-" not in final
