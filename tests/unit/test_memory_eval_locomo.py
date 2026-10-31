"""memory_eval 기능의 LoCoMo 어댑터: dia_id 를 세션에 잇고, 세션을 번호 순으로, 모르는 증거는 세션에서 뺀다."""

from jarvis.memory.eval.adapters import LOADERS, load_locomo
from tests.fixtures.memory_eval_helpers import LOCOMO_SAMPLE
from jarvis.memory.eval.adapters.locomo import parse_locomo


def test_locomo_parsing_maps_dia_ids_to_sessions_and_categories():
    qs = load_locomo(LOCOMO_SAMPLE)

    assert len(qs) == 2
    first = qs[0]
    assert first.question_type == "single-hop" and first.evidence_turn_ids == {"D1:1"}
    assert first.evidence_session_ids == {"conv-1:session_1"}
    assert first.sessions[1].turns[0].text.endswith("(사진: a sunny park)")
    assert first.sessions[0].turns[0].text.startswith("Caroline: ")
    assert qs[1].question_type == "adversarial" and qs[1].evidence_session_ids == set()
    assert set(LOADERS) == {"longmemeval", "locomo"}


def test_locomo_orders_sessions_numerically_and_drops_unknown_evidence():
    [q] = parse_locomo([{
        "sample_id": "c",
        "conversation": {
            "session_10": [{"speaker": "A", "text": "ten", "dia_id": "D10:1"}],
            "session_2": [{"speaker": "B", "text": "two", "dia_id": "D2:1"}],
            "session_2_date_time": "1:56 pm on 8 May, 2023",
        },
        "qa": [{"question": "q", "answer": 3, "category": 9, "evidence": ["D2:1", "D99:9"]}],
    }])

    assert [s.session_id for s in q.sessions] == ["c:session_2", "c:session_10"]
    assert q.sessions[0].date == "1:56 pm on 8 May, 2023" and q.sessions[1].date == ""
    assert q.question_type == "unknown" and q.answer == "3"
    assert q.evidence_turn_ids == {"D2:1", "D99:9"} and q.evidence_session_ids == {"c:session_2"}
