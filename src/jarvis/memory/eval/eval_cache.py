"""[memory] 벤치마크를 다시 돌려도 임베딩, 사실 추출, 판정을 다시 부르지 않게 결과를 디스크에 두는 캐시."""

import json
import array
import asyncio
import hashlib
import sqlite3
from typing import Any
from pathlib import Path
from collections.abc import Sequence

from jarvis.memory.consolidation.semantic_extract import Fact, FactExtractor
from jarvis.memory.eval.benchmark import BenchmarkQuestion, Judge
from jarvis.model_layer.embeddings import Embedder

EMBED_BATCH = 32  # Ollama bge-m3 는 묶어 보내면 1개 한 번과 거의 같은 시간이다. 긴 글이 섞이면 30초 제한에 걸려 줄였다
EMBED_TRIES = 3


def cache_key(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class CachedEmbedder(Embedder):
    """내용과 모델이 같으면 벡터를 sqlite 에서 읽는다. 벡터는 float32 로 담아 1024 차원 하나가 4KB 다."""

    def __init__(self, inner: Embedder, path: Path) -> None:
        self._inner = inner
        self.model = inner.model
        self.dimensions = inner.dimensions
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, vector BLOB NOT NULL)")
        self.calls = 0  # 실제로 안쪽 임베더에 보낸 텍스트 수
        # 로컬 Ollama 는 요청을 하나씩 처리한다. 동시에 몰리면 뒤 요청이 제한 시간을 넘기므로 한 줄로 세운다
        self._lock = asyncio.Lock()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        keys = [cache_key(self.model, t) for t in texts]
        found = self._load(keys)
        missing = [i for i, k in enumerate(keys) if k not in found]
        for start in range(0, len(missing), EMBED_BATCH):
            batch = missing[start : start + EMBED_BATCH]
            vectors = await self._embed_batch([texts[i] for i in batch])
            self.calls += len(batch)
            rows = [(keys[i], array.array("f", v).tobytes()) for i, v in zip(batch, vectors, strict=True)]
            self._db.executemany("INSERT OR REPLACE INTO vectors (key, vector) VALUES (?, ?)", rows)
            self._db.commit()
            for i, vector in zip(batch, vectors, strict=True):
                found[keys[i]] = vector
        return [found[k] for k in keys]

    async def _embed_batch(self, texts: list[str], tries: int = EMBED_TRIES) -> list[list[float]]:
        """실패하면 반으로 나눠 다시 보낸다. 긴 글 묶음이 제한 시간을 넘기는 경우다. 한 개도 실패하면 몇 번 더 본다."""
        try:
            async with self._lock:
                return await self._inner.embed(texts)
        except Exception:
            if len(texts) > 1:
                mid = len(texts) // 2
                return await self._embed_batch(texts[:mid], tries) + await self._embed_batch(texts[mid:], tries)
            if tries <= 1:
                raise
            return await self._embed_batch(texts, tries - 1)

    async def warm(self, texts: Sequence[str]) -> None:
        """한 번에 묶어 보내 캐시를 채운다. 메모리 쓰기 경로는 항목마다 하나씩 부르기 때문이다."""
        unique = list(dict.fromkeys(texts))
        for start in range(0, len(unique), EMBED_BATCH * 16):
            await self.embed(unique[start : start + EMBED_BATCH * 16])

    def close(self) -> None:
        self._db.close()

    def _load(self, keys: list[str]) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        unique = list(dict.fromkeys(keys))
        for start in range(0, len(unique), 500):
            chunk = unique[start : start + 500]
            marks = ",".join("?" * len(chunk))
            for key, blob in self._db.execute(f"SELECT key, vector FROM vectors WHERE key IN ({marks})", chunk):
                out[key] = array.array("f", blob).tolist()
        return out


class JsonlCache:
    """키 하나에 값 하나를 한 줄씩 덧붙인다. 같은 키를 다시 쓰면 마지막 줄이 이긴다."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._rows: dict[str, Any] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").split("\n"):
                if line.strip():
                    row = json.loads(line)
                    self._rows[row["key"]] = row["value"]
        path.parent.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> Any:
        return self._rows.get(key)

    def __contains__(self, key: str) -> bool:
        return key in self._rows

    def put(self, key: str, value: Any) -> None:
        self._rows[key] = value
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "value": value}, ensure_ascii=False) + "\n")


def cached_extractor(extractor: FactExtractor, cache: JsonlCache, namespace: str) -> FactExtractor:
    async def extract(text: str) -> list[Fact]:
        # ponytail: 추출기는 API 오류도 빈 목록이라 빈 결과까지 캐시한다, 오류가 보이면 캐시 파일에서 그 줄을 지운다
        key = cache_key("extract", namespace, text)
        if key not in cache:
            cache.put(key, [[f.key, f.value, f.importance] for f in await extractor(text)])
        return [Fact(key=k, value=v, importance=float(i)) for k, v, i in cache.get(key)]

    return extract


def cached_judge(judge: Judge, cache: JsonlCache, namespace: str) -> Judge:
    async def run(question: BenchmarkQuestion, retrieved: list[str]) -> tuple[str, bool]:
        key = cache_key("judge", namespace, question.question_id, question.question, question.answer,
                        question.choices, retrieved)
        if key not in cache:
            predicted, correct = await judge(question, retrieved)
            cache.put(key, [predicted, correct])
        predicted, correct = cache.get(key)
        return str(predicted), bool(correct)

    return run
