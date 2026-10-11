"""운영 슬래시 커맨드 핸들러 테스트 — /sessions, /branch, /tools, /compact."""
from __future__ import annotations

import pytest

from jarvis.model_layer.types import UserMessage

# ── /sessions ─────────────────────────────────────────────────────────────────

class TestSessionsHandler:
    async def test_empty(self, jsonl_repo):
        from jarvis.core.slash.ops_cmd import make_sessions_handler

        handler = make_sessions_handler(jsonl_repo)
        assert "저장된 세션이 없습니다" in await handler("")

    async def test_lists_sessions(self, jsonl_repo):
        from jarvis.core.slash.ops_cmd import make_sessions_handler

        await jsonl_repo.create(session_id="alpha")
        await jsonl_repo.create(session_id="beta")
        handler = make_sessions_handler(jsonl_repo)
        out = await handler("")
        assert "alpha" in out
        assert "beta" in out


# ── /branch ───────────────────────────────────────────────────────────────────

class TestBranchHandler:
    async def test_branch_creates_child(self, jsonl_repo):
        from jarvis.core.slash.ops_cmd import make_branch_handler

        await jsonl_repo.create(session_id="default")
        await jsonl_repo.append("default", UserMessage(content="hello"))
        handler = make_branch_handler(jsonl_repo)
        out = await handler("")
        assert "분기했습니다" in out

        sessions = await jsonl_repo.list("")
        assert any(s.parent_id == "default" for s in sessions)

    async def test_branch_unknown_parent(self, jsonl_repo):
        from jarvis.core.slash.ops_cmd import make_branch_handler

        handler = make_branch_handler(jsonl_repo)
        out = await handler("ghost-session")
        assert "찾을 수 없습니다" in out


# ── /tools ────────────────────────────────────────────────────────────────────

class TestToolsHandler:
    async def test_empty(self, tool_registry):
        from jarvis.core.slash.ops_cmd import make_tools_handler

        handler = make_tools_handler(tool_registry)
        assert "등록된 도구가 없습니다" in await handler("")

    async def test_lists_tools(self, tool_registry):
        from jarvis.core.slash.ops_cmd import make_tools_handler

        class T:
            name = "demo"
            description = "A demo tool\nsecond line ignored"
            parameters = {}
            execution_mode = "parallel"

            async def execute(self, *a, **k): ...

        tool_registry.register(T())
        handler = make_tools_handler(tool_registry)
        out = await handler("")
        assert "demo" in out
        assert "A demo tool" in out
        assert "second line ignored" not in out


# ── /compact ──────────────────────────────────────────────────────────────────

class TestCompactHandler:
    @pytest.fixture
    def ltm(self):
        from jarvis.memory.memory_service import MemoryService
        from jarvis.memory.stores.in_memory import InMemoryItemStore
        return MemoryService(InMemoryItemStore())

    @pytest.fixture
    def model_config(self):
        from jarvis.model_layer.types import ModelConfig
        return ModelConfig(provider="faux", model="faux-model")

    async def test_too_short(self, jsonl_repo, model_config, ltm):
        from jarvis.core.slash.ops_cmd import make_compact_handler

        await jsonl_repo.create(session_id="default")
        handler = make_compact_handler(model_config, jsonl_repo, ltm)
        assert "충분하지 않습니다" in await handler("")

    async def test_compacts_and_stores(self, jsonl_repo, model_config, ltm):
        from jarvis.core.slash.ops_cmd import make_compact_handler

        await jsonl_repo.create(session_id="default")
        await jsonl_repo.append("default", UserMessage(content="첫 메시지입니다"))
        await jsonl_repo.append("default", UserMessage(content="두 번째 메시지입니다"))

        handler = make_compact_handler(model_config, jsonl_repo, ltm)
        out = await handler("")
        assert "요약했습니다" in out

        stored = await ltm.recent(limit=5)
        assert len(stored) == 1
        assert stored[0].source == "manual_compact"
