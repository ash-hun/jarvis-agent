"""외부 벤치마크 어댑터와 실행기. 샘플 픽스처로 파싱과 raw 모드 증거 재현율을 검증한다."""

from pathlib import Path

from jarvis.memory.eval.judge import abstained, contains_judge, expects_abstention
from jarvis.memory.eval.benchmark import format_benchmark, run_benchmark, sample
from jarvis.memory.eval.adapters import LOADERS, load_locomo, load_longmemeval
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.eval.fake_embedder import FakeEmbedder
from jarvis.memory.memory_service import MemoryService

FIXTURES = Path(__file__).parents[2] / "fixtures" / "benchmarks"


def _factory() -> MemoryService:
    return MemoryService(InMemoryItemStore(), embedder=FakeEmbedder())


def test_longmemeval_parsing_keeps_session_and_turn_evidence():
    qs = load_longmemeval(FIXTURES / "longmemeval_sample.json")
    assert [q.question_id for q in qs] == ["q1", "q2_abs"]
    q1 = qs[0]
    assert q1.question_type == "single-session-user" and q1.evidence_session_ids == {"s-a"}
    assert q1.evidence_turn_ids == {"s-a#0"}
    assert [s.session_id for s in q1.sessions] == ["s-a", "s-b"] and q1.sessions[0].date.startswith("2023/05/20")
    assert qs[1].question_type == "abstention"  # _abs 접미사


def test_locomo_parsing_maps_dia_ids_to_sessions_and_categories():
    qs = load_locomo(FIXTURES / "locomo_sample.json")
    assert len(qs) == 2
    first = qs[0]
    assert first.question_type == "single-hop" and first.evidence_turn_ids == {"D1:1"}
    assert first.evidence_session_ids == {"conv-1:session_1"}
    assert first.sessions[1].turns[0].text.endswith("(사진: a sunny park)")
    assert first.sessions[0].turns[0].text.startswith("Caroline: ")
    assert qs[1].question_type == "adversarial" and qs[1].evidence_session_ids == set()
    assert set(LOADERS) == {"longmemeval", "locomo"}


async def test_raw_mode_recalls_evidence_session_and_turn():
    qs = load_longmemeval(FIXTURES / "longmemeval_sample.json")
    report = await run_benchmark("longmemeval", qs, _factory, k=3, judge=contains_judge())
    by_type = report.by_type()
    assert by_type["single-session-user"] == {"n": 1, "session_recall": 1.0, "turn_recall": 1.0, "accuracy": 1.0}
    assert by_type["abstention"]["session_recall"] == 0.0
    text = format_benchmark(report)
    assert "single-session-user" in text and "abstention" in text


async def test_locomo_raw_mode_turn_recall():
    qs = load_locomo(FIXTURES / "locomo_sample.json")
    report = await run_benchmark("locomo", qs, _factory, k=3)
    first = next(r for r in report.results if r.question_id == "conv-1:0")
    assert first.session_hit and first.turn_hit and first.correct is None


def test_sample_is_deterministic():
    qs = load_longmemeval(FIXTURES / "longmemeval_sample.json")
    assert sample(qs, 1, seed=7) == sample(qs, 1, seed=7)
    assert sample(qs, None) == qs


async def test_turns_mode_stores_a_turn_episode_per_exchange_and_keeps_turn_evidence():
    """발화와 답이 턴 일화 하나가 되고, 두 턴 id 가 태그로 남아 턴 재현율을 계산할 수 있다."""
    qs = load_longmemeval(FIXTURES / "longmemeval_sample.json")[:1]
    report = await run_benchmark("longmemeval", qs, _factory, k=3, mode="turns")
    result = report.results[0]
    assert result.retrieved and result.session_hit
    assert all(r.startswith("사용자: ") for r in result.retrieved)
    assert result.turn_hit is not None


def test_abstention_is_judged_by_code_not_by_the_judge_model():
    qs = load_longmemeval(FIXTURES / "longmemeval_sample.json")
    answerable, unanswerable = qs[0], qs[1]
    assert abstained("모름") and abstained(" 모름.") and not abstained("Business Administration")
    assert not expects_abstention(answerable) and expects_abstention(unanswerable)
