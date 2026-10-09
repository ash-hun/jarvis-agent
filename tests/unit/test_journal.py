"""Self-reflection 저널 (Tier 3 D2) — journaler + 명령."""
from __future__ import annotations

import pytest

from jarvis.agent_layer.journal import JOURNAL_SOURCE, ReflectionJournaler
from jarvis.agent_layer.thought.log import THOUGHT_SOURCE
from jarvis.memory.manager import MemoryManager
from jarvis.memory.stores.in_memory import InMemoryItemStore


async def _seed_thoughts(ltm, texts):
    for t in texts:
        await ltm.remember(t, source=THOUGHT_SOURCE)


@pytest.mark.asyncio
async def test_write_reflects_on_thoughts_and_stores(faux_model_with_response):
    ltm = MemoryManager(InMemoryItemStore())
    await _seed_thoughts(ltm, ['{"interpretation":"불안"}', '{"interpretation":"확신"}'])
    model = faux_model_with_response(response="반복적으로 사용자의 불안을 과대 해석하는 경향.")
    journaler = ReflectionJournaler(model, ltm)

    entry = await journaler.write()
    assert entry is not None and "과대 해석" in entry

    # 저널이 source="journal"로 LTM에 저장됐다.
    stored = [e for e in await ltm.recent(limit=20) if e.source == JOURNAL_SOURCE]
    assert len(stored) == 1
    assert stored[0].content == entry


@pytest.mark.asyncio
async def test_write_returns_none_without_thoughts(faux_model_with_response):
    ltm = MemoryManager(InMemoryItemStore())  # 사고 기록 없음
    model = faux_model_with_response(response="무언가")
    assert await ReflectionJournaler(model, ltm).write() is None


@pytest.mark.asyncio
async def test_recent_returns_only_journal_entries(faux_model_with_response):
    ltm = MemoryManager(InMemoryItemStore())
    await _seed_thoughts(ltm, ['{"x":1}'])
    await ltm.remember("일반 기억", source="explicit")
    model = faux_model_with_response(response="성찰 1")
    journaler = ReflectionJournaler(model, ltm)

    await journaler.write()
    recent = await journaler.recent()
    assert recent == ["성찰 1"]  # 사고·일반 기억 제외, 저널만


@pytest.mark.asyncio
async def test_journal_command(faux_model_with_response):
    from jarvis.core.slash.journal_cmd import make_journal_handler

    ltm = MemoryManager(InMemoryItemStore())
    await _seed_thoughts(ltm, ['{"interpretation":"x"}'])
    model = faux_model_with_response(response="메타 관찰 한 줄.")
    handler = make_journal_handler(ReflectionJournaler(model, ltm))

    assert "비어 있습니다" in await handler("")
    out = await handler("write")
    assert "메타 관찰" in out
    assert "메타 관찰" in await handler("")
