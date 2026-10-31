"""task_pattern: 패턴 규칙(키워드, 자연 키, 맞추기, 가르침)과 remember_task_pattern 도구의 에이전트 범위 저장을 검증."""

import pytest

from jarvis.memory.long_term.task_pattern import TaskPattern, best_matches, normalize_keywords, pattern_id, teaches
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.core.tools.task_pattern import TaskPatternTool
from jarvis.core.tools.tools_registry import ToolContext
from jarvis.memory import MemoryScope, MemoryService

KAREN = MemoryScope(user_id="u1", agent_id="karen", session_id="k1")
KAREN_LATER = MemoryScope(user_id="u1", agent_id="karen", session_id="k2")
MAIN = MemoryScope(user_id="u1", agent_id="main", session_id="m1")
BUDGET = TaskPattern(
    "예산 기반 공고 추천",
    "총예산과 현금으로 공고를 추천해 달라는 요청",
    "대출 = 총예산 이내 금액 - 현금. 금리는 연 4% 가정. housing_budget 으로 한 번에 찾는다",
    ("예산", "현금", "월 상환", "추천"),
)
PARAMS = {
    "name": "예산 기반 공고 추천",
    "when": "총예산과 현금으로 공고 추천 요청",
    "steps": "대출 = 총예산 - 현금, 금리 4%",
    "keywords": "예산, 현금, 추천",
}


def test_normalize_keywords_dedupes_lowercases_and_drops_one_char_words():
    assert normalize_keywords("예산, 현금 ,예산, 월, ") == ("예산", "현금")
    assert normalize_keywords(["Budget", "budget"]) == ("budget",)


def test_pattern_id_is_a_natural_key():
    assert pattern_id(KAREN, "예산 기반  공고 추천") == pattern_id(KAREN_LATER, "예산 기반 공고 추천")
    assert pattern_id(KAREN, "예산 기반 공고 추천") != pattern_id(MAIN, "예산 기반 공고 추천")


def test_best_matches_works_with_korean_particles():
    assert best_matches([BUDGET], "3억 예산으로 현금 1억 2천이면 추천해줘", 2) == [BUDGET]
    assert best_matches([BUDGET], "오늘 날씨 어때", 2) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("앞으로 비슷한 요청이 오면 기억해", True),
        ("다음부터 이렇게 계산해", True),
        ("이 방식으로 해", True),
        ("LH 공고 찾아줘", False),
    ],
)
def test_teaches_detects_teaching_words(text, expected):
    assert teaches(text) is expected


async def test_tool_saves_in_the_calling_agent_scope():
    memory = MemoryService(InMemoryItemStore())

    result = await TaskPatternTool(memory).execute("t1", PARAMS, context=ToolContext(scope=KAREN, session_id="k1"))

    assert not result.is_error and "karen" in result.content[0].text
    assert [p.name for p in await memory.task_patterns(KAREN)] == ["예산 기반 공고 추천"]
    assert await memory.task_patterns(MAIN) == []


async def test_tool_rejects_missing_fields():
    memory = MemoryService(InMemoryItemStore())

    result = await TaskPatternTool(memory).execute("t1", {**PARAMS, "keywords": "a"}, context=ToolContext(scope=KAREN))

    assert result.is_error
    assert await memory.task_patterns(KAREN) == []


async def test_tool_refuses_without_a_caller_scope():
    memory = MemoryService(InMemoryItemStore())

    result = await TaskPatternTool(memory).execute("t1", PARAMS)

    assert result.is_error and "범위" in result.content[0].text
