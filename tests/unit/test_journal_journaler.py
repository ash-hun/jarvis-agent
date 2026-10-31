"""journal: journaler 가 사고 로그를 성찰해 저널로 남기고 저널만 돌려주며 저장 실패와 빈 답을 견디는지 검증."""

import pytest

from jarvis.agent_layer.journal import JOURNAL_SOURCE, ReflectionJournaler
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.agent_layer.thought.log import THOUGHT_SOURCE
from jarvis.memory.memory_service import MemoryService
from jarvis.memory.scope import MemoryScope

SCOPE = MemoryScope(user_id="local")


async def _seed_thoughts(ltm, texts):
    for t in texts:
        await ltm.remember(t, source=THOUGHT_SOURCE, scope=SCOPE)


@pytest.mark.asyncio
async def test_write_reflects_on_thoughts_and_stores_one_entry(faux_model_with_response):
    ltm = MemoryService(InMemoryItemStore())
    await _seed_thoughts(ltm, ['{"interpretation":"불안"}', '{"interpretation":"확신"}'])
    model = faux_model_with_response(response="반복적으로 사용자의 불안을 과대 해석하는 경향.")
    journaler = ReflectionJournaler(model, ltm)

    entry = await journaler.write(SCOPE)
    assert entry is not None and "과대 해석" in entry

    # 저널이 source="journal"로 LTM에 저장됐다.
    stored = [e for e in await ltm.recent(SCOPE, limit=20) if e.source == JOURNAL_SOURCE]
    assert len(stored) == 1
    assert stored[0].content == entry


@pytest.mark.asyncio
async def test_write_returns_none_without_thoughts(faux_model_with_response):
    ltm = MemoryService(InMemoryItemStore())  # 사고 기록 없음
    model = faux_model_with_response(response="무언가")
    assert await ReflectionJournaler(model, ltm).write(SCOPE) is None


@pytest.mark.asyncio
async def test_recent_returns_only_journal_entries(faux_model_with_response):
    ltm = MemoryService(InMemoryItemStore())
    await _seed_thoughts(ltm, ['{"x":1}'])
    await ltm.remember("일반 기억", source="explicit", scope=SCOPE)
    model = faux_model_with_response(response="성찰 1")
    journaler = ReflectionJournaler(model, ltm)

    await journaler.write(SCOPE)
    recent = await journaler.recent(SCOPE)
    assert recent == ["성찰 1"]  # 사고·일반 기억 제외, 저널만


class _Entry:
    def __init__(self, content: str, source: str) -> None:
        self.content = content
        self.source = source


class _StubMemory:
    """recent/remember 만 흉내 낸다. remember 실패를 고를 수 있다."""

    def __init__(self, entries: list[_Entry], fail_remember: bool = False) -> None:
        self.entries = entries
        self.fail_remember = fail_remember
        self.remembered: list[tuple[str, str]] = []
        self.limits: list[int] = []

    async def recent(self, scope: MemoryScope, limit: int = 20) -> list[_Entry]:
        self.limits.append(limit)
        return self.entries[:limit]

    async def remember(self, text: str, source: str, scope: MemoryScope) -> None:
        if self.fail_remember:
            raise RuntimeError("store down")
        self.remembered.append((text, source))


@pytest.mark.asyncio
async def test_write_returns_text_even_if_remember_fails(faux_model_with_response):
    memory = _StubMemory([_Entry("{}", THOUGHT_SOURCE)], fail_remember=True)
    model = faux_model_with_response(response="  성찰  ")
    assert await ReflectionJournaler(model, memory).write(SCOPE) == "성찰"  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_write_returns_none_on_blank_model_output(faux_model_with_response):
    memory = _StubMemory([_Entry("{}", THOUGHT_SOURCE)])
    model = faux_model_with_response(response="   ")
    assert await ReflectionJournaler(model, memory).write(SCOPE) is None  # type: ignore[arg-type]
    assert memory.remembered == []


@pytest.mark.asyncio
async def test_recent_scans_up_to_scan_limit_and_returns_limit(faux_model_with_response):
    entries = [_Entry(f"j{i}", JOURNAL_SOURCE) for i in range(4)]
    memory = _StubMemory(entries)
    journaler = ReflectionJournaler(faux_model_with_response(response="x"), memory, scan_limit=3)  # type: ignore[arg-type]
    assert await journaler.recent(SCOPE, limit=2) == ["j0", "j1"]
    assert memory.limits == [3]
