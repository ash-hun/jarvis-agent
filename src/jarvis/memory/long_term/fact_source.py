"""[memory] 추출한 사실의 출처 일화를 고르고 그 일화에서 사실과 가장 겹치는 부분을 잘라 내는 순수 함수."""

import re
from collections.abc import Callable, Sequence

from jarvis.memory.stores.store_protocol import tokens_of
from jarvis.memory.memory_types import MemoryItem
from jarvis.model_layer.embeddings import cosine

SOURCE_EPISODE = "from_episode"  # 의미 사실 metadata: 그 사실을 뽑아낸 일화 id(출처)
SOURCE_CHARS = 300  # 회상 때 사실 아래 붙이는 출처 발췌의 최대 글자 수
SOURCE_MARK = "↳ 출처:"
_SENTENCE_END = re.compile(r"(?<=[.!?。])\s+|\n+")


def pick_source(
    fact: str, episodes: Sequence[MemoryItem], text: Callable[[MemoryItem], str] = lambda e: e.content
) -> MemoryItem | None:
    """사실 낱말이 text(일화) 에 가장 많이 나오는 일화. 같으면 앞의 것. 겹치는 낱말이 없으면 None."""
    words = set(tokens_of(fact))
    best, best_hits = None, 0
    for episode in episodes:
        hits = _hits(words, text(episode))
        if hits > best_hits:
            best, best_hits = episode, hits
    return best


def nearest_episode(vector: Sequence[float], episodes: Sequence[MemoryItem]) -> MemoryItem | None:
    """벡터가 가장 가까운 일화. 사실을 대화와 다른 말로 뽑으면(영어 대화, 한국어 사실) 낱말이 겹치지 않는다."""
    scored = [(cosine(list(vector), e.embedding), -i, e) for i, e in enumerate(episodes) if e.embedding]
    return max(scored, key=lambda t: (t[0], t[1]))[2] if scored else None


def source_excerpt(fact: str, text: str, limit: int = SOURCE_CHARS) -> str:
    """text 에서 사실 낱말이 가장 많은 문장을 중심으로 이웃 문장을 붙여 limit 자 안쪽으로 자른다."""
    sentences = [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]
    if not sentences:
        return ""
    words = set(tokens_of(fact))
    center = max(range(len(sentences)), key=lambda i: (_hits(words, sentences[i]), -i))
    start = end = center
    size = len(sentences[center])
    # 앞뒤 중 짧은 쪽부터 붙여 중심 문장이 발췌 가운데에 오게 한다
    while True:
        options: list[tuple[int, str]] = []
        if start > 0:
            options.append((len(sentences[start - 1]) + 1, "before"))
        if end + 1 < len(sentences):
            options.append((len(sentences[end + 1]) + 1, "after"))
        options = [(n, side) for n, side in options if size + n <= limit]
        if not options:
            break
        n, side = min(options)
        size += n
        if side == "before":
            start -= 1
        else:
            end += 1
    return " ".join(sentences[start : end + 1])[:limit]


def with_source(content: str, excerpt: str | None) -> str:
    """회상 블록 한 줄. 출처가 없거나 지워졌으면 사실만."""
    if not excerpt:
        return content
    return f"{content}\n  {SOURCE_MARK} {' '.join(excerpt.split())}"


def _hits(words: set[str], text: str) -> int:
    lowered = text.lower()
    return sum(1 for w in words if w in lowered)
