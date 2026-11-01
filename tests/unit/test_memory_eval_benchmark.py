"""memory_eval 기능의 외부 벤치마크 실행기: raw 와 turns 모드 증거 재현율, 결정적 표본."""

import pytest

from jarvis.memory.eval.benchmark import (
    MODES,
    BenchmarkQuestion,
    Retrieved,
    fit_budget,
    format_benchmark,
    run_benchmark,
    sample,
    stratified_sample,
)
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
    assert by_type["abstention"]["session_recall"] is None  # 증거 세션이 없는 질문은 재현율에서 뺀다
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


async def test_rag_mode_needs_an_embedder_and_scores_chunks():
    qs = load_longmemeval(LONGMEMEVAL_SAMPLE)

    report = await run_benchmark("longmemeval", qs, _factory, k=3, mode="rag", embedder=FakeEmbedder())

    assert report.results[0].session_hit and report.results[0].turn_hit
    with pytest.raises(ValueError):
        await run_benchmark("longmemeval", qs, _factory, mode="rag")


async def test_budget_caps_exposed_chars_for_every_mode():
    qs = load_longmemeval(LONGMEMEVAL_SAMPLE)

    for mode in MODES:
        report = await run_benchmark("longmemeval", qs, _factory, mode=mode, embedder=FakeEmbedder(), budget=120)
        assert all(r.exposed_chars <= 120 for r in report.results)
        assert report.summary()["mean_chars"] <= 120


def test_fit_budget_clips_the_last_item_and_stops():
    items = [Retrieved("a" * 50, "s", frozenset()), Retrieved("b" * 50, "s", frozenset()),
             Retrieved("c", "s", frozenset())]

    assert [r.text for r in fit_budget(items, 5, 70)] == ["a" * 50, "b" * 20]
    assert len(fit_budget(items, 2, None)) == 2


def test_stratified_sample_spreads_types_and_is_deterministic():
    qs = [BenchmarkQuestion(f"{t}{i}", t, "q", "a", [], corpus_id=f"c{i % 3}") for t in "xyz" for i in range(6)]

    picked = stratified_sample(qs, 6, seed=1)

    assert sorted(q.question_type for q in picked) == ["x", "x", "y", "y", "z", "z"]
    assert picked == stratified_sample(qs, 6, seed=1)
    assert {q.corpus for q in stratified_sample(qs, None, seed=1, max_corpora=1)} in ({"c0"}, {"c1"}, {"c2"})


async def test_fixed_mode_puts_core_facts_first_then_k_recalled_items():
    qs = load_longmemeval(LONGMEMEVAL_SAMPLE)[:1]

    def factory() -> MemoryService:
        return MemoryService(InMemoryItemStore(), embedder=FakeEmbedder(), fixed_facts=0)

    report = await run_benchmark("longmemeval", qs, factory, k=2, mode="raw", fixed=True)

    assert 1 <= len(report.results[0].retrieved) <= 2 and report.results[0].session_hit
