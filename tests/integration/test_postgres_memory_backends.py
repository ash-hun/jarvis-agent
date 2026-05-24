"""PostgresSTMBackend + PostgresLTMBackend 통합 테스트.

testcontainers로 실제 PostgreSQL 컨테이너를 띄워 검증한다.
Docker가 없거나 testcontainers/asyncpg가 설치되지 않으면 자동 skip.
"""

from __future__ import annotations

import pytest

testcontainers = pytest.importorskip("testcontainers", reason="testcontainers not installed")
pytest.importorskip("asyncpg", reason="asyncpg not installed")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def postgres_dsn():
    from testcontainers.postgres import PostgresContainer

    try:
        with PostgresContainer("postgres:16-alpine") as pg:
            dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
            yield dsn
    except Exception as exc:
        pytest.skip(f"Docker unavailable or container failed to start: {exc}")


@pytest.fixture
async def stm(postgres_dsn: str):
    from jarvis.agent_layer.memory.backends.postgres_stm import PostgresSTMBackend

    b = PostgresSTMBackend(dsn=postgres_dsn)
    yield b
    await b.close()


@pytest.fixture
async def ltm(postgres_dsn: str):
    from jarvis.agent_layer.memory.backends.postgres_ltm import PostgresLTMBackend

    b = PostgresLTMBackend(dsn=postgres_dsn)
    yield b
    await b.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _user_msg(text: str):
    from jarvis.model_layer.types import UserMessage
    return UserMessage(content=text)


def _asst_msg(text: str):
    from jarvis.model_layer.types import AssistantMessage, TextContent, Usage
    return AssistantMessage(
        content=[TextContent(text=text)],
        provider="faux",
        model="faux-model",
        usage=Usage(),
        stop_reason="stop",
    )


# ── PostgresSTMBackend ────────────────────────────────────────────────────────

class TestPostgresSTM:
    async def test_append_and_load(self, stm):
        await stm.append("s1", _user_msg("hello"))
        await stm.append("s1", _asst_msg("hi there"))

        msgs = await stm.load("s1")
        assert len(msgs) == 2
        assert msgs[0].content == "hello"
        assert msgs[1].content[0].text == "hi there"

    async def test_sessions_are_isolated(self, stm):
        await stm.append("iso-a", _user_msg("session a"))
        await stm.append("iso-b", _user_msg("session b"))

        assert len(await stm.load("iso-a")) == 1
        assert (await stm.load("iso-a"))[0].content == "session a"
        assert len(await stm.load("iso-b")) == 1

    async def test_clear(self, stm):
        await stm.append("clr", _user_msg("msg"))
        await stm.clear("clr")
        assert await stm.load("clr") == []

    async def test_load_empty(self, stm):
        assert await stm.load("nonexistent-stm-session") == []

    async def test_close_and_reopen(self, postgres_dsn):
        from jarvis.agent_layer.memory.backends.postgres_stm import PostgresSTMBackend

        b = PostgresSTMBackend(dsn=postgres_dsn)
        await b.append("reopen", _user_msg("before close"))
        await b.close()

        b2 = PostgresSTMBackend(dsn=postgres_dsn)
        msgs = await b2.load("reopen")
        assert len(msgs) == 1
        await b2.close()


# ── PostgresLTMBackend ────────────────────────────────────────────────────────

class TestPostgresLTM:
    async def test_store_and_get_recent(self, ltm):
        from jarvis.agent_layer.memory.backends.protocol import MemoryEntry

        e = MemoryEntry(content="Python 배우기", source="explicit")
        await ltm.store(e)

        recent = await ltm.get_recent(limit=5)
        contents = [r.content for r in recent]
        assert "Python 배우기" in contents

    async def test_search_keyword(self, ltm):
        from jarvis.agent_layer.memory.backends.protocol import MemoryEntry

        await ltm.store(MemoryEntry(content="LangChain 튜토리얼", source="explicit"))
        await ltm.store(MemoryEntry(content="Python 기초 문법", source="explicit"))

        results = await ltm.search("LangChain")
        assert any("LangChain" in r.content for r in results)

    async def test_search_case_insensitive(self, ltm):
        from jarvis.agent_layer.memory.backends.protocol import MemoryEntry

        await ltm.store(MemoryEntry(content="FastAPI 정리", source="explicit"))
        results = await ltm.search("fastapi")
        assert any("FastAPI" in r.content for r in results)

    async def test_search_no_match(self, ltm):
        from jarvis.agent_layer.memory.backends.protocol import MemoryEntry

        await ltm.store(MemoryEntry(content="FastAPI 가이드", source="explicit"))
        results = await ltm.search("Django999")
        assert results == []

    async def test_delete(self, ltm):
        from jarvis.agent_layer.memory.backends.protocol import MemoryEntry

        e = MemoryEntry(content="삭제할 항목", source="explicit")
        entry_id = await ltm.store(e)
        await ltm.delete(entry_id)

        recent = await ltm.get_recent(limit=100)
        assert all(r.id != entry_id for r in recent)

    async def test_store_upsert(self, ltm):
        from jarvis.agent_layer.memory.backends.protocol import MemoryEntry

        e = MemoryEntry(content="원본", source="explicit")
        await ltm.store(e)

        e2 = MemoryEntry(id=e.id, content="업데이트", source="explicit")
        await ltm.store(e2)

        recent = await ltm.get_recent(limit=100)
        matched = [r for r in recent if r.id == e.id]
        assert len(matched) == 1
        assert matched[0].content == "업데이트"

    async def test_clear_all(self, ltm):
        from jarvis.agent_layer.memory.backends.protocol import MemoryEntry

        for i in range(3):
            await ltm.store(MemoryEntry(content=f"항목 {i}", source="explicit"))
        await ltm.clear_all()
        assert await ltm.get_recent() == []
