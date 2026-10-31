"""memory 기능의 의미 기억 정책: "주제: 값" 주제 추출과 주제가 다른 비슷한 사실의 간섭 후보."""

import pytest

from jarvis.memory.long_term.semantic import fact_key, find_interference, similarity
from jarvis.memory import MemoryItem, MemoryKind, MemoryScope
from jarvis.memory.consolidation.semantic_extract import Fact

SCOPE = MemoryScope(user_id="u1", agent_id="main", session_id="s1")


def _fact(content: str) -> MemoryItem:
    return MemoryItem(content=content, kind=MemoryKind.SEMANTIC, scope=SCOPE)


@pytest.mark.parametrize(
    ("content", "expected"),
    [(Fact("주력 언어", "Python").content, "주력 언어"), ("콜론 없음", None), ("x" * 50 + ": y", None)],
    ids=["fact_content", "no_colon", "key_too_long"],
)
def test_fact_key_reads_topic_of_key_colon_value(content, expected):
    assert fact_key(content) == expected


def test_find_interference_pairs_similar_facts_with_different_keys():
    a, b, c = _fact("출근 수단: 지하철로 출근"), _fact("통근 방법: 지하철로 출근"), _fact("반려견 이름: 보리")

    assert similarity(a.content, b.content) >= 0.5
    assert find_interference([a, b, c], threshold=0.5) == [(a.id, b.id)]


def test_find_interference_leaves_same_topic_to_supersede():
    a, d = _fact("출근 수단: 지하철로 출근"), _fact("출근 수단: 버스로 출근")

    assert find_interference([a, d], threshold=0.1) == []
