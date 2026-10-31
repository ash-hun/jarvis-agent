"""작업 패턴 기억: 사용자가 알려 준 방식을 에이전트 전용으로 저장하고, 같은 종류 요청에 그 에이전트에게만 떠올린다."""

import pytest

from jarvis.memory.long_term.task_pattern import (
    PATTERN_HEADER,
    SAVE_HINT_HEADER,
    TaskPattern,
    best_matches,
    normalize_keywords,
    pattern_id,
    teaches,
)
from jarvis.memory import MemoryKind, MemoryScope, MemoryService
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.model_layer.types import UserMessage

KAREN = MemoryScope(user_id="u1", agent_id="karen", session_id="k1")
KAREN_LATER = MemoryScope(user_id="u1", agent_id="karen", session_id="k2")
MAIN = MemoryScope(user_id="u1", agent_id="main", session_id="m1")
BUDGET = TaskPattern(
    "예산 기반 공고 추천",
    "총예산과 현금으로 공고를 추천해 달라는 요청",
    "대출 = 총예산 이내 금액 - 현금. 금리는 연 4% 가정. housing_budget 으로 한 번에 찾는다",
    ("예산", "현금", "월 상환", "추천"),
)


@pytest.fixture
def memory() -> MemoryService:
    return MemoryService(InMemoryItemStore())


def _context(scope: MemoryScope) -> dict:
    return {"user_id": scope.user_id, "agent_id": scope.agent_id, "session_id": scope.session_id}


async def _observe(memory: MemoryService, scope: MemoryScope, text: str) -> list[str]:
    out = await memory.observe([UserMessage(content=text, timestamp=0)], _context(scope))
    return [m.content for m in out[:-1]]


def test_keywords_are_normalized():
    assert normalize_keywords("예산, 현금 ,예산, 월, ") == ("예산", "현금")
    assert normalize_keywords(["Budget", "budget"]) == ("budget",)


def test_pattern_id_is_a_natural_key():
    assert pattern_id(KAREN, "예산 기반  공고 추천") == pattern_id(KAREN_LATER, "예산 기반 공고 추천")
    assert pattern_id(KAREN, "예산 기반 공고 추천") != pattern_id(MAIN, "예산 기반 공고 추천")


def test_matching_works_with_korean_particles():
    assert best_matches([BUDGET], "3억 예산으로 현금 1억 2천이면 추천해줘", 2) == [BUDGET]
    assert best_matches([BUDGET], "오늘 날씨 어때", 2) == []


@pytest.mark.parametrize("text", ["앞으로 비슷한 요청이 오면 기억해", "다음부터 이렇게 계산해", "이 방식으로 해"])
def test_teaching_words(text):
    assert teaches(text)


def test_plain_request_is_not_teaching():
    assert not teaches("LH 공고 찾아줘")


async def test_saved_as_agent_private_procedural(memory):
    item_id = await memory.remember_pattern(BUDGET, KAREN)
    item = await memory.get(item_id)
    assert (item.kind, item.author) == (MemoryKind.PROCEDURAL, "user")
    assert item.scope.agent_id == "karen" and item.scope.session_id is None


async def test_saving_twice_keeps_one_and_updates(memory):
    await memory.remember_pattern(BUDGET, KAREN)
    changed = TaskPattern(BUDGET.name, BUDGET.when, "금리는 연 3.5% 가정", BUDGET.keywords)
    await memory.remember_pattern(changed, KAREN_LATER)
    patterns = await memory.task_patterns(KAREN)
    assert [p.steps for p in patterns] == ["금리는 연 3.5% 가정"]


async def test_other_agent_does_not_see_or_recall_it(memory):
    await memory.remember_pattern(BUDGET, KAREN)
    assert await memory.task_patterns(MAIN) == []
    blocks = await _observe(memory, MAIN, "예산 3억 현금 1억으로 공고 추천해줘")
    assert not any(b.startswith(PATTERN_HEADER) for b in blocks)


async def test_same_agent_recalls_in_a_new_session(memory):
    await memory.remember_pattern(BUDGET, KAREN)
    blocks = await _observe(memory, KAREN_LATER, "예산 3억 현금 1억으로 공고 추천해줘")
    pattern = next(b for b in blocks if b.startswith(PATTERN_HEADER))
    assert "대출 = 총예산 이내 금액 - 현금" in pattern
    # 일반 회상 블록에 같은 내용이 또 들어가지 않는다
    assert not any(b.startswith("[장기 기억]") and "예산 기반 공고 추천" in b for b in blocks)


async def test_unrelated_request_gets_no_pattern(memory):
    await memory.remember_pattern(BUDGET, KAREN)
    assert not any(b.startswith(PATTERN_HEADER) for b in await _observe(memory, KAREN_LATER, "SH 공고 보여줘"))


async def test_teaching_message_gets_a_save_hint(memory):
    blocks = await _observe(memory, KAREN, "앞으로 비슷한 요청이 오면 이렇게 계산해. 기억해")
    assert any(b.startswith(SAVE_HINT_HEADER) and "remember_task_pattern" in b for b in blocks)


async def test_forget_pattern(memory):
    await memory.remember_pattern(BUDGET, KAREN)
    assert await memory.forget_pattern(BUDGET.name, KAREN_LATER)
    assert await memory.task_patterns(KAREN) == []
    assert not await memory.forget_pattern(BUDGET.name, KAREN)
