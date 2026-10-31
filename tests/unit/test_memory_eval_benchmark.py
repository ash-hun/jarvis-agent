"""memory_eval 기능의 외부 벤치마크 실행기: raw 와 turns 모드 증거 재현율, 결정적 표본."""

from jarvis.memory.eval.benchmark import format_benchmark, run_benchmark, sample
from tests.fixtures.memory_eval_helpers import LOCOMO_SAMPLE, LONGMEMEVAL_SAMPLE
from jarvis.memory.eval.adapters import load_locomo, load_longmemeval
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.eval.fake_embedder import FakeEmbedder
from jarvis.memory.memory_service import MemoryService
from jarvis.memory.eval.judge import contains_judge


def _factory() -> MemoryService:
    return MemoryService(InMemoryItemStore(), embedder=FakeEmbedder())


async def test_raw_mode_recalls_evidence_session_and_turn():
    qs = load_longmemeval(LONGMEMEVAL_SAMPLE)

    report = await run_benchmark("longmemeval", qs, _factory, k=3, judge=contains_judge())

    by_type = report.by_type()
    assert by_type["single-session-user"] == {"n": 1, "session_recall": 1.0, "turn_recall": 1.0, "accuracy": 1.0}
    assert by_type["abstention"]["session_recall"] == 0.0
    text = format_benchmark(report)
    assert "single-session-user" in text and "abstention" in text


async def test_locomo_raw_mode_turn_recall_without_judge():
    qs = load_locomo(LOCOMO_SAMPLE)

    report = await run_benchmark("locomo", qs, _factory, k=3)

    first = next(r for r in report.results if r.question_id == "conv-1:0")
    assert first.session_hit and first.turn_hit and first.correct is None


async def test_turns_mode_stores_a_turn_episode_per_exchange_and_keeps_turn_evidence():
    """발화와 답이 턴 일화 하나가 되고, 두 턴 id 가 태그로 남아 턴 재현율을 계산할 수 있다."""
    qs = load_longmemeval(LONGMEMEVAL_SAMPLE)[:1]

    report = await run_benchmark("longmemeval", qs, _factory, k=3, mode="turns")

    result = report.results[0]
    assert result.retrieved and result.session_hit
    assert all(r.startswith("사용자: ") for r in result.retrieved)
    assert result.turn_hit is not None


def test_sample_is_deterministic():
    qs = load_longmemeval(LONGMEMEVAL_SAMPLE)

    assert sample(qs, 1, seed=7) == sample(qs, 1, seed=7)
    assert sample(qs, None) == qs
