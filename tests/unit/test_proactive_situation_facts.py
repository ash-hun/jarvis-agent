"""proactive 의 situation_facts: 이벤트 글과 약속 기한에서 남은 시간과 처리 신호를 계산하고, 못 읽으면 모름으로 둔다."""

import pytest
from datetime import datetime

from jarvis.core.proactive.situation_facts import (
    event_fact,
    handled_signal,
    loop_fact,
    mentioned_time,
    situation_facts,
)

NOW = datetime(2026, 1, 1, 9, 0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("[bank] 자동이체 예정(오늘 10:00)", (0, 60)),
        ("[calendar] 일정 변경: 10:30 → 09:30", (0, 30)),
        ("[ci] build failed at 08:52", (0, -8)),
        ("[slack] 9시 반 배포 창", (0, 30)),
        ("[mail] 오후 2시 회의", (0, 300)),
        ("[calendar] 미팅 2026-01-15 10:00", (14, 14 * 1440 + 60)),
        ("연말정산 마감 1월 15일", (14, None)),
        ("[notice] 12월 31일 점검", (-1, None)),
        ("[ad] 할인 1,284,300원 3 failed", (None, None)),
        ("[x] 25:99 같은 시각", (None, None)),
    ],
    ids=["today", "nearest_future", "past", "half", "pm", "iso", "date_only", "last_year_day", "no_time", "invalid"],
)
def test_mentioned_time(text, expected) -> None:  # type: ignore[no-untyped-def]
    assert mentioned_time(text, NOW) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("[calendar] 김서연 님이 초대를 수락했습니다.", "수락"),
        ("[ci] re-run passed (all checks)", "완료"),
        ("[calendar] 미팅이 취소되었습니다", "취소"),
        ("[bank] 결제 실패 - 잔액 부족", None),
        ("제출 완료 여부 미확인", None),
        ("[accepted] 새 메일", None),
    ],
    ids=["accept", "done", "cancel", "failure_wins", "unresolved", "tag_ignored"],
)
def test_handled_signal(text, expected) -> None:  # type: ignore[no-untyped-def]
    assert handled_signal(text) == expected


def test_loop_fact_prefers_due_over_text() -> None:
    fact = loop_fact("보고 (기한 10:00)", datetime(2026, 1, 1, 9, 20), NOW)

    assert (fact.source, fact.days, fact.minutes) == ("loop", 0, 20)


def test_situation_facts_keeps_order_and_unknowns() -> None:
    facts = situation_facts([("회고 자료", None)], ["[ad] 쿠폰"], NOW)

    assert [(f.source, f.minutes, f.signal) for f in facts] == [("loop", None, None), ("event", None, None)]
    assert event_fact("[ad] 쿠폰", NOW).view()["within_30_min"] == "unknown"
