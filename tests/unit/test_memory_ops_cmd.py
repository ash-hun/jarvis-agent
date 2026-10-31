"""memory 기능의 운영 명령: /sessions, /branch, /tools 표시와 /compact 요약의 장기 기억 저장."""

import pytest

from jarvis.core.slash.ops_cmd import (
    make_branch_handler,
    make_compact_handler,
    make_sessions_handler,
    make_tools_handler,
)
from jarvis.model_layer.model_types import ModelConfig, UserMessage
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.memory_service import MemoryService
from jarvis.memory.scope import MemoryScope

SCOPE = MemoryScope(user_id="local", session_id="default")
MODEL = ModelConfig(provider="faux", model="faux-model")


class _Tool:
    name = "demo"
    description = "A demo tool\nsecond line ignored"
    parameters: dict = {}
    execution_mode = "parallel"

    async def execute(self, *a, **k): ...


@pytest.fixture
def ltm() -> MemoryService:
    return MemoryService(InMemoryItemStore())


async def test_sessions_without_saved_session_says_empty(jsonl_repo):
    assert "저장된 세션이 없습니다" in await make_sessions_handler(jsonl_repo)("")


async def test_sessions_lists_every_session(jsonl_repo):
    await jsonl_repo.create(session_id="alpha")
    await jsonl_repo.create(session_id="beta")

    out = await make_sessions_handler(jsonl_repo)("")

    assert "alpha" in out and "beta" in out


async def test_branch_creates_child_of_default_session(jsonl_repo):
    await jsonl_repo.create(session_id="default")
    await jsonl_repo.append("default", UserMessage(content="hello"))

    out = await make_branch_handler(jsonl_repo)("")

    assert "분기했습니다" in out
    assert any(s.parent_id == "default" for s in await jsonl_repo.list(""))


async def test_branch_unknown_parent_is_refused(jsonl_repo):
    assert "찾을 수 없습니다" in await make_branch_handler(jsonl_repo)("ghost-session")


async def test_tools_without_registered_tool_says_empty(tool_registry):
    assert "등록된 도구가 없습니다" in await make_tools_handler(tool_registry)("")


async def test_tools_lists_first_description_line_only(tool_registry):
    tool_registry.register(_Tool())

    out = await make_tools_handler(tool_registry)("")

    assert "demo" in out and "A demo tool" in out
    assert "second line ignored" not in out


async def test_compact_too_short_session_is_refused(jsonl_repo, ltm):
    await jsonl_repo.create(session_id="default")

    assert "충분하지 않습니다" in await make_compact_handler(MODEL, jsonl_repo, ltm)("", SCOPE)


async def test_compact_stores_summary_in_long_term_memory(jsonl_repo, ltm):
    await jsonl_repo.create(session_id="default")
    await jsonl_repo.append("default", UserMessage(content="첫 메시지입니다"))
    await jsonl_repo.append("default", UserMessage(content="두 번째 메시지입니다"))

    out = await make_compact_handler(MODEL, jsonl_repo, ltm)("", SCOPE)

    assert "요약했습니다" in out
    stored = await ltm.recent(SCOPE, limit=5)
    assert len(stored) == 1
    assert stored[0].source == "manual_compact"
    assert stored[0].scope == SCOPE
