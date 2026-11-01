"""memory_eval 기능: 같은 질문을 네 비교군으로 담고 묻고 판정한 뒤 RAG 대비 benefit, tax 를 세는 파이프라인."""

import json

from jarvis.memory.eval.eval_cache import JsonlCache, cached_extractor, cached_judge
from jarvis.memory.eval.benchmark import MODES, BenchmarkQuestion, run_benchmark
from tests.fixtures.memory_eval_helpers import LONGMEMEVAL_SAMPLE
from jarvis.memory.consolidation.semantic_extract import Fact
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.eval.fake_embedder import FakeEmbedder
from jarvis.memory.eval.adapters import load_longmemeval
from jarvis.memory.memory_service import MemoryService
from jarvis.memory.eval.net_value import net_value


async def _extract(text: str) -> list[Fact]:
    return [Fact("거주지", "부산", 0.9)] if "부산" in text else []


async def _judge(question: BenchmarkQuestion, retrieved: list[str]) -> tuple[str, bool]:
    joined = "\n".join(retrieved)
    return joined[:50], bool(question.answer) and question.answer in joined


async def test_four_arms_share_the_judge_budget_and_yield_net_value(tmp_path):
    questions = load_longmemeval(LONGMEMEVAL_SAMPLE)
    cache = JsonlCache(tmp_path / "cache.jsonl")
    extractor = cached_extractor(_extract, cache, "fake")
    judge = cached_judge(_judge, cache, "fake")

    def factory() -> MemoryService:
        return MemoryService(InMemoryItemStore(), extractor=extractor, embedder=FakeEmbedder())

    reports = {
        mode: await run_benchmark("lme", questions, factory, mode=mode, judge=judge, embedder=FakeEmbedder(),
                                  budget=400, concurrency=2)
        for mode in MODES
    }

    assert all(r.summary()["mean_chars"] <= 400 for r in reports.values())
    assert reports["rag"].results[0].correct and reports["raw"].results[0].correct
    src = reports["turns+src"].results[0].retrieved
    # 출처 턴이 함께 떠오르면 발췌를 붙이지 않고, 안 떠오르면 사실 아래 붙는다. 어느 쪽이든 원문이 보인다
    fact = next(line for line in src if line.startswith("거주지: 부산"))
    assert "↳ 출처: 나는 작년에 부산으로 이사했어" in fact or any("나는 작년에 부산으로" in line for line in src)
    assert not any("↳ 출처" in line for line in reports["turns"].results[0].retrieved)
    value = net_value(reports["rag"], reports["turns+src"])
    assert value.n == 2 and value.net == value.benefit - value.tax
    json.dumps(reports["turns"].to_dict(), ensure_ascii=False)


async def test_running_again_reads_the_cache_and_gives_the_same_report(tmp_path):
    questions = load_longmemeval(LONGMEMEVAL_SAMPLE)
    calls: list[str] = []

    async def counting(question: BenchmarkQuestion, retrieved: list[str]) -> tuple[str, bool]:
        calls.append(question.question_id)
        return await _judge(question, retrieved)

    judge = cached_judge(counting, JsonlCache(tmp_path / "judge.jsonl"), "fake")

    def factory() -> MemoryService:
        return MemoryService(InMemoryItemStore(), embedder=FakeEmbedder())

    first = await run_benchmark("lme", questions, factory, mode="raw", judge=judge, budget=300)
    second = await run_benchmark("lme", questions, factory, mode="raw", judge=judge, budget=300)

    assert first.to_dict() == second.to_dict() and len(calls) == len(questions)
