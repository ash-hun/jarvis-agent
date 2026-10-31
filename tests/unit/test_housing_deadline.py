"""housing: deadline 이 추천 공고의 마감 전 약속을 알릴 날에 공고마다 하나만 남기고 닫힌 약속은 되살리지 않는지 검증."""

import pytest
import asyncio
from datetime import date, datetime

from jarvis.core.tools.housing.deadline import deadline_loop, loop_id, remind_date, track_deadlines
from jarvis.agent_layer.openloop import InMemoryOpenLoopStore
from jarvis.core.tools.housing.lh_notice import Notice

NOTICE = Notice("1-03-06-10", "행복주택", "테스트 공고", "경기도", "2026.10.01", "2026.10.20", "공고중")
TODAY = date(2026, 10, 13)


@pytest.mark.parametrize(
    ("closes", "remind"),
    [
        (date(2026, 10, 20), date(2026, 10, 17)),
        (date(2026, 10, 15), date(2026, 10, 14)),
        # 내일 마감이면 방금 한 답으로 충분하다
        (date(2026, 10, 14), None),
        (date(2026, 10, 13), None),
    ],
)
def test_remind_date_is_three_days_before_or_the_day_before_or_none(closes, remind):
    assert remind_date(closes, TODAY) == remind


def test_deadline_loop_is_due_at_nine_in_the_morning_kst():
    loop = deadline_loop(NOTICE, "s1", "karen", TODAY)

    assert loop is not None and loop.id == loop_id("s1", NOTICE.id) and loop.agent_id == "karen"
    assert loop.due_ms == int(datetime.fromisoformat("2026-10-17T09:00:00+09:00").timestamp() * 1000)
    assert "테스트 공고" in loop.description and "2026-10-20" in loop.description


def test_track_deadlines_twice_keeps_one_loop_and_does_not_reopen_a_closed_one():
    store = InMemoryOpenLoopStore()

    assert asyncio.run(track_deadlines(store, [NOTICE], "s1", "karen", TODAY)) == [NOTICE]
    assert asyncio.run(track_deadlines(store, [NOTICE], "s1", "karen", TODAY)) == []
    assert len(asyncio.run(store.all())) == 1
    asyncio.run(store.update_status(loop_id("s1", NOTICE.id), "dismissed"))
    assert asyncio.run(track_deadlines(store, [NOTICE], "s1", "karen", TODAY)) == []
    assert asyncio.run(store.list_open()) == []
