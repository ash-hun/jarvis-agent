"""memory 기능의 단서 겹침 점수: 범위(세션, 에이전트) 일치와 태그 주제 일치의 평균."""

import pytest

from jarvis.memory.memory_types import MemoryItem, MemoryKind
from jarvis.memory.retrieval.cues import cue_overlap
from jarvis.memory.scope import MemoryScope

SCOPE = MemoryScope(user_id="u1", agent_id="main", session_id="s1")


@pytest.mark.parametrize(
    ("item_scope", "tags", "query", "expected"),
    [
        (SCOPE, [], "아무 질의", 0.5),
        (SCOPE.with_session("other"), [], "아무 질의", 0.25),
        (MemoryScope(user_id="u1", agent_id="coder"), [], "거주지", 0.0),
        (SCOPE, ["key:거주지"], "거주지", 1.0),
        (SCOPE, ["key:거주지"], "거주지 어디", (1.0 + 0.5) / 2),
        (SCOPE, ["key:거주지"], "", 0.5),
    ],
    ids=["same_session", "same_agent", "other_agent", "tag_hit", "tag_half_hit", "no_query"],
)
def test_cue_overlap_averages_context_and_tag_match(item_scope, tags, query, expected):
    item = MemoryItem(content="x", kind=MemoryKind.SEMANTIC, scope=item_scope, tags=tags)

    assert cue_overlap(item, SCOPE, query) == expected
