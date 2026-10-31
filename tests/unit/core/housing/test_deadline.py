"""추천한 공고의 마감 전 약속: 알릴 날, 공고마다 하나, 닫힌 약속은 되살리지 않음, housing_budget 배선."""

import asyncio
from datetime import date, datetime

from jarvis.core.tools.housing.deadline import deadline_loop, loop_id, remind_date, track_deadlines
from tests.fixtures.housing_board import TODAY, Board, budget_tool, page
from jarvis.agent_layer.openloop import InMemoryOpenLoopStore
from jarvis.core.tools.tools_registry import ToolContext
from jarvis.core.tools.housing.lh_notice import Notice
from jarvis.memory.scope import MemoryScope

NOTICE = Notice("1-03-06-10", "행복주택", "테스트 공고", "경기도", "2026.10.01", "2026.10.20", "공고중")


def test_remind_three_days_before_or_the_day_before_or_not_at_all():
    today = date(2026, 10, 13)
    assert remind_date(date(2026, 10, 20), today) == date(2026, 10, 17)
    assert remind_date(date(2026, 10, 15), today) == date(2026, 10, 14)  # 사흘이 안 남으면 전날
    assert remind_date(date(2026, 10, 14), today) is None  # 내일 마감이면 방금 한 답으로 충분하다
    assert remind_date(date(2026, 10, 13), today) is None


def test_loop_is_due_at_nine_in_the_morning_kst():
    loop = deadline_loop(NOTICE, "s1", "karen", date(2026, 10, 13))
    assert loop is not None and loop.id == loop_id("s1", NOTICE.id) and loop.agent_id == "karen"
    assert loop.due_ms == int(datetime.fromisoformat("2026-10-17T09:00:00+09:00").timestamp() * 1000)
    assert "테스트 공고" in loop.description and "2026-10-20" in loop.description


def test_tracking_twice_keeps_one_loop_and_does_not_reopen_a_closed_one():
    store = InMemoryOpenLoopStore()
    today = date(2026, 10, 13)
    assert asyncio.run(track_deadlines(store, [NOTICE], "s1", "karen", today)) == [NOTICE]
    assert asyncio.run(track_deadlines(store, [NOTICE], "s1", "karen", today)) == []
    assert len(asyncio.run(store.all())) == 1
    asyncio.run(store.update_status(loop_id("s1", NOTICE.id), "dismissed"))
    assert asyncio.run(track_deadlines(store, [NOTICE], "s1", "karen", today)) == []
    assert asyncio.run(store.list_open()) == []


def test_budget_leaves_a_deadline_loop_for_the_top_pick_and_says_so():
    store = InMemoryOpenLoopStore()
    tool = budget_tool(Board(pdf_text=page("rent_terms_uiwang.txt")))
    tool._loops = store
    context = ToolContext(scope=MemoryScope(user_id="u", agent_id="karen", session_id="s1"), session_id="s1")
    params = {"budget": 3e8, "cash": 1.2e8, "monthly_limit": 2e6}

    text = asyncio.run(tool.execute("t1", params, context=context)).content[0].text
    [loop] = asyncio.run(store.list_open(session_id="s1"))
    assert "의왕청계2 A1블록" in loop.description and loop.agent_id == "karen"
    assert text.endswith("마감 3일 전 아침에 다시 알려 드릴게요.") and date.fromtimestamp(loop.due_ms / 1000) > TODAY

    # 같은 추천을 다시 받아도 약속은 하나이고, 다시 알리겠다는 말도 되풀이하지 않는다
    again = asyncio.run(tool.execute("t2", params, context=context)).content[0].text
    assert len(asyncio.run(store.all())) == 1 and "다시 알려 드릴게요" not in again


def test_scheduled_and_test_sessions_leave_no_deadline_loop():
    """목표 차례(sched-)와 시험 세션은 끝나면 아무도 약속을 꺼내지 않는다. 남기지 않고, 결과 글도 매번 같다."""
    store = InMemoryOpenLoopStore()
    tool = budget_tool(Board(pdf_text=page("rent_terms_uiwang.txt")))
    tool._loops = store
    params = {"budget": 3e8, "cash": 1.2e8, "monthly_limit": 2e6}
    texts = []
    for sid in ("sched-goal-abc-1", "sched-goal-abc-2", "test-goal-1"):
        context = ToolContext(scope=MemoryScope(user_id="u", agent_id="karen", session_id=sid), session_id=sid)
        texts.append(asyncio.run(tool.execute("t", params, context=context)).content[0].text)
    assert asyncio.run(store.all()) == [] and len(set(texts)) == 1 and "다시 알려 드릴게요" not in texts[0]
