"""memory_eval 기능의 LongMemEval 어댑터: 세션과 턴 증거 보존, 빠진 id 와 날짜의 대체값."""

from jarvis.memory.eval.adapters.longmemeval import parse_longmemeval
from tests.fixtures.memory_eval_helpers import LONGMEMEVAL_SAMPLE
from jarvis.memory.eval.adapters import load_longmemeval


def test_longmemeval_parsing_keeps_session_and_turn_evidence():
    qs = load_longmemeval(LONGMEMEVAL_SAMPLE)

    assert [q.question_id for q in qs] == ["q1", "q2_abs"]
    q1 = qs[0]
    assert q1.question_type == "single-session-user" and q1.evidence_session_ids == {"s-a"}
    assert q1.evidence_turn_ids == {"s-a#0"}
    assert [s.session_id for s in q1.sessions] == ["s-a", "s-b"] and q1.sessions[0].date.startswith("2023/05/20")
    assert qs[1].question_type == "abstention"  # _abs 접미사


def test_longmemeval_missing_ids_and_dates_fall_back():
    [q] = parse_longmemeval([{
        "question_id": 7,
        "question": "q?",
        "haystack_sessions": [[{"content": "hello", "has_answer": True}], [{"role": "assistant", "content": "x"}]],
        "haystack_session_ids": ["only-one"],
    }])

    assert q.question_id == "7" and q.question_type == "unknown" and q.answer == ""
    assert [s.session_id for s in q.sessions] == ["only-one", "session_1"]
    assert [s.date for s in q.sessions] == ["", ""]
    assert q.sessions[0].turns[0].role == "user" and q.evidence_turn_ids == {"only-one#0"}
    assert q.evidence_session_ids == set()
