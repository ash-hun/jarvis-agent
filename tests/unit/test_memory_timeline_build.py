"""memory: 집계형 질문을 가리고 대상별 일화를 시간순 타임라인으로 짓는지 검증."""

import pytest
from datetime import datetime

from jarvis.memory.retrieval.timeline_build import is_aggregate, mentions, render_timeline, snippet
from jarvis.memory import MemoryItem, MemoryKind, MemoryScope

SCOPE = MemoryScope(user_id="u1", agent_id="main")


def _ep(content: str, day: int, turn: int = 1) -> MemoryItem:
    return MemoryItem(content=content, kind=MemoryKind.EPISODIC, scope=SCOPE, created_at=datetime(2026, 1, day),
                      metadata={"turn": turn})


@pytest.mark.parametrize(("question", "expected"), [
    ("How many times has Mary moved?", True),
    ("List in chronological order all locations", True),
    ("Emma 랑 몇 번 만났지?", True),
    ("What is my favorite color?", False),
    ("치과 예약 어디로 했어?", False),
])
def test_is_aggregate(question, expected):
    assert is_aggregate(question) is expected


def test_mentions_keeps_text_matches_in_time_and_turn_order():
    items = [_ep("Mary went to the garden", 3), _ep("John slept", 1), _ep("mary moved to office", 1, turn=2),
             _ep("Mary is in the hallway", 1, turn=1)]

    assert [i.content for i in mentions("Mary", items)] == [
        "Mary is in the hallway", "mary moved to office", "Mary went to the garden",
    ]


def test_render_timeline_counts_all_and_keeps_latest_when_over():
    items = [_ep(f"Mary step {n}", n) for n in range(1, 6)]

    text = render_timeline("Mary", items, max_lines=2)

    assert text.splitlines() == [
        "[대상 타임라인] Mary: 언급 5건, 오래된 것부터(최근 2건만)",
        "- [2026-01-04] Mary step 4",
        "- [2026-01-05] Mary step 5",
    ]
    assert render_timeline("Mary", []) == ""


def test_snippet_centers_on_name_and_marks_cuts():
    text = "a " * 60 + "Mary moved" + " b" * 60
    piece = snippet(text, "Mary", width=20)
    assert "Mary" in piece and piece.startswith("…") and piece.endswith("…")
