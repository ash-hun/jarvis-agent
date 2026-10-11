"""검색 점수: recency 감쇠, relevance 비율, 단서 겹침, 종류별 순위."""

from datetime import datetime, timedelta

from jarvis.memory import MemoryItem, MemoryKind, MemoryScope
from jarvis.memory.retrieval import cue_overlap, rank, relevance
from jarvis.memory.retrieval.scoring import recency

SCOPE = MemoryScope(user_id="u1", agent_id="main", session_id="s1")
NOW = datetime(2026, 10, 9, 12, 0)


def _item(
    content: str, kind=MemoryKind.SEMANTIC, days_ago: float = 0, importance: float = 0.5, rehearsal_count: int = 0, **kw
) -> MemoryItem:
    return MemoryItem(
        content=content, kind=kind, scope=SCOPE, importance=importance, rehearsal_count=rehearsal_count,
        created_at=NOW - timedelta(days=days_ago), **kw,
    )


def test_recency_halves_every_half_life():
    fresh, week, two_weeks = _item("a"), _item("b", days_ago=7), _item("c", days_ago=14)
    assert recency(fresh, NOW) == 1.0
    assert abs(recency(week, NOW, 168.0) - 0.5) < 1e-9
    assert abs(recency(two_weeks, NOW, 168.0) - 0.25) < 1e-9


def test_recency_uses_last_access_when_present():
    item = _item("a", days_ago=30)
    item.last_accessed = NOW
    assert recency(item, NOW) == 1.0


def test_relevance_is_fraction_of_query_tokens_found():
    assert relevance("배포 실패 원인", "배포가 실패했고 원인은 환경변수") == 1.0
    assert relevance("거주지 직장", "거주지: 부산") == 0.5
    assert relevance("", "x") == 0.0


def test_cue_overlap_rewards_same_session_and_tag_match():
    same_session = _item("x", tags=["key:거주지"])
    other_agent = MemoryItem(content="y", kind=MemoryKind.SEMANTIC, scope=MemoryScope(user_id="u1", agent_id="r"))
    assert cue_overlap(same_session, SCOPE, "거주지") == 1.0  # 세션 일치 1.0, 태그 1.0
    assert cue_overlap(other_agent, SCOPE, "거주지") == 0.0


def test_episodic_rank_prefers_recent_when_equally_relevant():
    old = _item("회의: 예산 논의", MemoryKind.EPISODIC, days_ago=30)
    new = _item("회의: 일정 논의", MemoryKind.EPISODIC, days_ago=1)
    assert rank([old, new], "회의", SCOPE, 2) == [new, old]


def test_semantic_rank_prefers_relevant_over_recent():
    recent_but_off = _item("선호 음료: 커피", days_ago=0)
    old_but_exact = _item("거주지 직장: 부산 알파", days_ago=60)
    assert rank([recent_but_off, old_but_exact], "거주지 직장", SCOPE, 1) == [old_but_exact]


def test_importance_breaks_ties():
    a = _item("선호: 커피 아침", importance=0.9)
    b = _item("선호: 커피 파랑", importance=0.1)
    assert rank([b, a], "선호 커피", SCOPE, 1) == [a]


# ── importance 감쇠와 되뇌기 저항 ─────────────────────────────────────────────


def test_importance_decays_with_age_unless_rehearsed():
    from jarvis.memory.retrieval import NO_DECAY, ScoringParams, effective_importance

    params = ScoringParams(importance_half_life_hours=24 * 90, rehearsal_k=3)
    fresh = _item("a", importance=0.8)
    old = _item("b", importance=0.8, days_ago=90)
    old_rehearsed = _item("c", importance=0.8, days_ago=90, rehearsal_count=30)
    assert effective_importance(fresh, NOW, params) == 0.8
    assert abs(effective_importance(old, NOW, params) - 0.4) < 1e-9  # 반감기 한 번
    assert effective_importance(old_rehearsed, NOW, params) > 0.75  # 되뇌기가 보존한다
    assert effective_importance(old, NOW, NO_DECAY) == 0.8


def test_rehearsed_old_fact_outranks_unrehearsed_twin():
    from jarvis.memory.retrieval import ScoringParams

    params = ScoringParams()
    a = _item("선호 음식: 김치찌개", days_ago=400, importance=0.8, rehearsal_count=12)
    b = _item("선호 음식 메모: 김치찌개 된장찌개", days_ago=400, importance=0.8)
    assert rank([b, a], "선호 음식 김치찌개", SCOPE, 1, now=NOW, params=params) == [a]


def test_relevance_uses_cosine_when_both_vectors_present():
    assert relevance("x", "y", [1.0, 0.0], [1.0, 0.0]) == 1.0
    assert relevance("x", "y", [1.0, 0.0], [-1.0, 0.0]) == 0.0  # 음수는 0 으로
    assert relevance("거주지", "거주지: 부산", None, [1.0]) == 1.0  # 한쪽만 있으면 키워드
