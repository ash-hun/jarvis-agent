"""합성 점수. Generative Agents 의 recency + importance + relevance 에 부호화 단서 겹침을 더한다."""

import math
from dataclasses import dataclass
from datetime import datetime

from jarvis.memory.retrieval.cues import cue_overlap
from jarvis.memory.scope import MemoryScope
from jarvis.memory.stores.protocol import tokens_of
from jarvis.memory.types import MemoryItem, MemoryKind

DEFAULT_HALF_LIFE_HOURS = 24.0 * 7  # 일주일 지나면 recency 가 절반


@dataclass(frozen=True)
class Weights:
    recency: float
    importance: float
    relevance: float
    cue: float


# 종류별 기본 가중치. 의미는 "맞는 사실"이 중요하고, 일화는 "최근 일"이 중요하다.
KIND_WEIGHTS: dict[MemoryKind, Weights] = {
    MemoryKind.SEMANTIC: Weights(recency=0.1, importance=0.2, relevance=0.6, cue=0.1),
    MemoryKind.EPISODIC: Weights(recency=0.4, importance=0.2, relevance=0.3, cue=0.1),
    MemoryKind.PROCEDURAL: Weights(recency=0.0, importance=0.1, relevance=0.8, cue=0.1),
}


def recency(item: MemoryItem, now: datetime, half_life_hours: float = DEFAULT_HALF_LIFE_HOURS) -> float:
    """최근 회상(점화) 또는 생성 시각 기준 지수 감쇠. 0..1."""
    anchor = item.last_accessed or item.occurred_at or item.created_at
    hours = max(0.0, (now - anchor).total_seconds() / 3600)
    return math.pow(0.5, hours / half_life_hours) if half_life_hours > 0 else 1.0


def relevance(query: str, content: str) -> float:
    """질의 토큰 중 내용에 등장하는 비율. 벡터 유사도로 바꿀 자리는 이 함수 하나다."""
    tokens = tokens_of(query)
    if not tokens:
        return 0.0
    lowered = content.lower()
    return sum(1 for t in tokens if t in lowered) / len(tokens)


def score(
    item: MemoryItem,
    query: str,
    scope: MemoryScope,
    now: datetime | None = None,
    weights: Weights | None = None,
    half_life_hours: float = DEFAULT_HALF_LIFE_HOURS,
) -> float:
    now = now or datetime.now()
    w = weights or KIND_WEIGHTS[item.kind]
    return (
        w.recency * recency(item, now, half_life_hours)
        + w.importance * item.importance
        + w.relevance * relevance(query, item.content)
        + w.cue * cue_overlap(item, scope, query)
    )


def rank(
    items: list[MemoryItem],
    query: str,
    scope: MemoryScope,
    limit: int,
    now: datetime | None = None,
    half_life_hours: float = DEFAULT_HALF_LIFE_HOURS,
) -> list[MemoryItem]:
    now = now or datetime.now()
    scored = sorted(
        items,
        key=lambda i: (score(i, query, scope, now, half_life_hours=half_life_hours), i.created_at),
        reverse=True,
    )
    return scored[:limit]
