"""memory_eval 기능의 결과 캐시: 다시 돌리면 임베딩, 추출, 판정을 다시 부르지 않는다."""

from jarvis.memory.eval.eval_cache import CachedEmbedder, JsonlCache, cached_extractor, cached_judge
from jarvis.memory.consolidation.semantic_extract import Fact
from jarvis.memory.eval.benchmark import BenchmarkQuestion
from jarvis.memory.eval.fake_embedder import FakeEmbedder


class _Counting(FakeEmbedder):
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.seen += texts
        return await super().embed(texts)


async def test_cached_embedder_survives_reopen_and_only_embeds_new_texts(tmp_path):
    inner = _Counting()
    first = CachedEmbedder(inner, tmp_path / "e.sqlite")
    vectors = await first.embed(["거주지 부산", "점심 김밥"])
    first.close()

    again = CachedEmbedder(inner, tmp_path / "e.sqlite")
    await again.warm(["거주지 부산", "새 문장", "새 문장"])

    assert await again.embed(["거주지 부산"]) == [vectors[0]]
    assert inner.seen == ["거주지 부산", "점심 김밥", "새 문장"] and again.calls == 1


async def test_cached_extractor_and_judge_call_the_model_once(tmp_path):
    calls: list[str] = []

    async def extractor(text: str) -> list[Fact]:
        calls.append(text)
        return [Fact("거주지", "부산", 0.9)]

    async def judge(question: BenchmarkQuestion, retrieved: list[str]) -> tuple[str, bool]:
        calls.append(question.question_id)
        return "부산", True

    cache = JsonlCache(tmp_path / "c.jsonl")
    extract, ask = cached_extractor(extractor, cache, "m"), cached_judge(judge, cache, "m")
    question = BenchmarkQuestion("q1", "t", "어디 살아", "부산", [])
    for _ in range(2):
        assert await extract("부산 산다") == [Fact("거주지", "부산", 0.9)]
        assert await ask(question, ["거주지: 부산"]) == ("부산", True)

    assert calls == ["부산 산다", "q1"]
    assert JsonlCache(tmp_path / "c.jsonl").get("없는 키") is None
