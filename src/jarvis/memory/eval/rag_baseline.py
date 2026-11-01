"""[memory] 원문 턴을 조각으로 묶어 임베딩 코사인 top-k 만으로 찾는 naive RAG 비교군(Memory Tax 의 기준선)."""

from typing import TYPE_CHECKING
from dataclasses import dataclass
from collections.abc import Sequence

from jarvis.model_layer.embeddings import Embedder, cosine

if TYPE_CHECKING:
    from jarvis.memory.eval.benchmark import BenchmarkQuestion, BenchmarkSession

# Memory Tax(He et al. 2026) 부록 A.2 의 naive RAG 조각 규칙. 재순위기와 BM25 는 빼고 임베딩 코사인만 본다
CHUNK_CHARS = 1024  # 짧은 턴은 이 길이 안쪽까지 묶는다
WINDOW_CHARS = 8192  # 이보다 긴 턴은 창으로 자른다
WINDOW_OVERLAP = 1024


@dataclass(frozen=True)
class RagChunk:
    text: str
    session_id: str
    turn_ids: tuple[str, ...]


def chunk_sessions(sessions: Sequence["BenchmarkSession"]) -> list[RagChunk]:
    """세션 경계를 넘지 않게 턴을 묶는다. 짧은 턴은 약 1024자까지 묶고 앞 조각의 마지막 턴을 겹쳐 둔다.

    1024자보다 긴 턴은 혼자 조각이 되고, 8192자보다 길면 1024자 겹침의 8192자 창으로 자른다.
    조각마다 세션 날짜를 머리말로 붙인다.
    """
    chunks: list[RagChunk] = []
    for session in sessions:
        header = f"[{session.date}]\n" if session.date else ""
        current: list[tuple[str, str]] = []  # (턴 id, 본문)
        for turn in session.turns:
            text = f"[{turn.role}] {turn.text}"
            if len(text) > CHUNK_CHARS:
                if current:
                    chunks.append(_chunk(header, session.session_id, current))
                    current = []
                for window in _windows(text):
                    chunks.append(RagChunk(header + window, session.session_id, (turn.turn_id,)))
                continue
            if current and sum(len(t) for _, t in current) + len(text) > CHUNK_CHARS:
                chunks.append(_chunk(header, session.session_id, current))
                carried = current[-1]
                current = [carried] if len(carried[1]) + len(text) <= CHUNK_CHARS else []
            current.append((turn.turn_id, text))
        if current:
            chunks.append(_chunk(header, session.session_id, current))
    return chunks


class RagIndex:
    """질문 하나의 대화 전체를 조각으로 담고 질의 벡터와의 코사인 순으로 돌려준다."""

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder
        self._chunks: list[RagChunk] = []
        self._vectors: list[list[float]] = []

    async def ingest(self, question: "BenchmarkQuestion") -> None:
        self._chunks = chunk_sessions(question.sessions)
        self._vectors = await self._embedder.embed([c.text for c in self._chunks]) if self._chunks else []

    async def search(self, query: str, k: int) -> list[RagChunk]:
        if not self._chunks or not query.strip():
            return []
        vector = (await self._embedder.embed([query]))[0]
        order = sorted(range(len(self._chunks)), key=lambda i: (-cosine(vector, self._vectors[i]), i))
        return [self._chunks[i] for i in order[:k]]


def _chunk(header: str, session_id: str, turns: list[tuple[str, str]]) -> RagChunk:
    return RagChunk(header + "\n".join(t for _, t in turns), session_id, tuple(i for i, _ in turns))


def _windows(text: str) -> list[str]:
    if len(text) <= WINDOW_CHARS:
        return [text]
    step = WINDOW_CHARS - WINDOW_OVERLAP
    return [text[start : start + WINDOW_CHARS] for start in range(0, len(text) - WINDOW_OVERLAP, step)]
