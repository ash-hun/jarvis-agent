"""[memory] Generative Agents 의 recency, importance, relevance 에 단서 겹침을 더한 합성 점수(순수 함수)."""

import math
from datetime import datetime
from dataclasses import dataclass

from jarvis.memory.types import MemoryItem, MemoryKind
from jarvis.memory.retrieval.cues import cue_overlap
from jarvis.memory.stores.protocol import tokens_of
from jarvis.model_layer.embeddings import cosine
from jarvis.memory.scope import MemoryScope

DEFAULT_HALF_LIFE_HOURS = 24.0 * 7  # 일주일 지나면 recency 가 절반
# importance 는 저장값을 깎지 않고 검색 시점에 감쇠시킨다. 저장값을 주기적으로 깎으면 재실행마다 상태가 달라진다
DEFAULT_IMPORTANCE_HALF_LIFE_HOURS = 24.0 * 90  # 석 달 지나면 importance 가 절반(되뇌기 없을 때)
DEFAULT_REHEARSAL_K = 3.0  # 되뇌기 포화 상수. 3회면 보존력이 절반
# 섬광 기억 자리: 저장된 importance 가 이 이상이고 질의와 분명히 맞는 항목 하나는 나이와 무관하게 결과에 남긴다.
# 일화는 recency 비중이 커서, 같은 낱말의 어제 일 여럿이 몇 달 전의 큰 사건을 항상 밀어낸다
SALIENT_IMPORTANCE = 0.8
# 느슨하게 닮은 질의마다 큰 사건이 끼어들지 않게(과잉일반화) 질의 토큰의 이 비율 이상이 내용에 있을 때만 자리를 준다.
# 코사인은 짧은 질의와 긴 내용 사이에서 0.4 안팎이라 같은 문턱으로 잴 수 없어 토큰 비율 하나로만 본다
SALIENT_MIN_RELEVANCE = 0.5


@dataclass(frozen=True)
class Weights:
    recency: float
    importance: float
    relevance: float
    cue: float


@dataclass(frozen=True)
class ScoringParams:
    recency_half_life_hours: float = DEFAULT_HALF_LIFE_HOURS
    importance_half_life_hours: float = DEFAULT_IMPORTANCE_HALF_LIFE_HOURS  # 0 이면 감쇠 없음
    rehearsal_k: float = DEFAULT_REHEARSAL_K


DEFAULT_PARAMS = ScoringParams()
NO_DECAY = ScoringParams(importance_half_life_hours=0.0)

# 종류별 기본 가중치. 의미는 "맞는 사실"이 중요하고, 일화는 "최근 일"이 중요하다.
KIND_WEIGHTS: dict[MemoryKind, Weights] = {
    MemoryKind.SEMANTIC: Weights(recency=0.1, importance=0.2, relevance=0.6, cue=0.1),
    MemoryKind.EPISODIC: Weights(recency=0.4, importance=0.2, relevance=0.3, cue=0.1),
    MemoryKind.PROCEDURAL: Weights(recency=0.0, importance=0.1, relevance=0.8, cue=0.1),
}


def _age_hours(item: MemoryItem, now: datetime) -> float:
    anchor = item.last_accessed or item.occurred_at or item.created_at
    return max(0.0, (now - anchor).total_seconds() / 3600)


def recency(item: MemoryItem, now: datetime, half_life_hours: float = DEFAULT_HALF_LIFE_HOURS) -> float:
    """최근 회상(점화) 또는 생성 시각 기준 지수 감쇠. 0..1."""
    return math.pow(0.5, _age_hours(item, now) / half_life_hours) if half_life_hours > 0 else 1.0


def effective_importance(item: MemoryItem, now: datetime, params: ScoringParams = DEFAULT_PARAMS) -> float:
    """저장된 importance 를 나이로 감쇠시키되, 되뇌기 횟수만큼 감쇠에 저항한다. 0..1.

    retention = rehearsal / (rehearsal + k). 한 번도 떠올리지 않은 항목은 반감기대로 잊히고,
    자주 떠올린 항목은 원값에 가깝게 남는다(환자 HM 의 절차 기억처럼 반복이 보존을 만든다).
    """
    if params.importance_half_life_hours <= 0:
        return item.importance
    decay = math.pow(0.5, _age_hours(item, now) / params.importance_half_life_hours)
    retention = item.rehearsal_count / (item.rehearsal_count + params.rehearsal_k) if params.rehearsal_k > 0 else 1.0
    return item.importance * (decay + (1.0 - decay) * retention)


def relevance(
    query: str,
    content: str,
    query_embedding: list[float] | None = None,
    item_embedding: list[float] | None = None,
) -> float:
    """질의와 내용의 관련도 0..1. 양쪽 벡터가 있으면 코사인, 아니면 질의 토큰이 내용에 등장하는 비율."""
    if query_embedding is not None and item_embedding is not None:
        return max(0.0, cosine(query_embedding, item_embedding))
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
    params: ScoringParams = DEFAULT_PARAMS,
    query_embedding: list[float] | None = None,
) -> float:
    now = now or datetime.now()
    w = weights or KIND_WEIGHTS[item.kind]
    return (
        w.recency * recency(item, now, params.recency_half_life_hours)
        + w.importance * effective_importance(item, now, params)
        + w.relevance * relevance(query, item.search_text, query_embedding, item.embedding)
        + w.cue * cue_overlap(item, scope, query)
    )


def rank(
    items: list[MemoryItem],
    query: str,
    scope: MemoryScope,
    limit: int,
    now: datetime | None = None,
    params: ScoringParams = DEFAULT_PARAMS,
    query_embedding: list[float] | None = None,
) -> list[MemoryItem]:
    now = now or datetime.now()
    scored = sorted(
        items,
        key=lambda i: (score(i, query, scope, now, params=params, query_embedding=query_embedding), i.created_at),
        reverse=True,
    )
    top = scored[:limit]
    if limit < 2 or any(i.importance >= SALIENT_IMPORTANCE for i in top):
        return top
    salient = next(
        (
            i for i in scored[limit:]
            if i.importance >= SALIENT_IMPORTANCE
            and relevance(query, i.search_text) >= SALIENT_MIN_RELEVANCE
        ),
        None,
    )
    return top if salient is None else [*top[:-1], salient]
