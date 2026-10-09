"""PostgresSTMBackend + PostgresItemStore 통합 테스트.

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
    from jarvis.memory.manager import MemoryManager
    from jarvis.memory.stores.postgres import PostgresItemStore

    store = PostgresItemStore(dsn=postgres_dsn)
    yield MemoryManager(store)
    await store.close()


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


# ── PostgresItemStore ────────────────────────────────────────────────────────

class TestPostgresLTM:
    async def test_store_and_get_recent(self, ltm):
        await ltm.remember("Python 배우기", source="explicit")

        recent = await ltm.recent(limit=5)
        contents = [r.content for r in recent]
        assert "Python 배우기" in contents

    async def test_search_keyword(self, ltm):
        await ltm.remember("LangChain 튜토리얼", source="explicit")
        await ltm.remember("Python 기초 문법", source="explicit")

        results = await ltm.recall("LangChain")
        assert any("LangChain" in r.content for r in results)

    async def test_search_case_insensitive(self, ltm):
        await ltm.remember("FastAPI 정리", source="explicit")
        results = await ltm.recall("fastapi")
        assert any("FastAPI" in r.content for r in results)

    async def test_search_no_match(self, ltm):
        await ltm.remember("FastAPI 가이드", source="explicit")
        results = await ltm.recall("Django999")
        assert results == []

    async def test_delete(self, ltm):
        entry_id = await ltm.remember("삭제할 항목", source="explicit")
        await ltm.forget(entry_id)

        recent = await ltm.recent(limit=100)
        assert all(r.id != entry_id for r in recent)

    async def test_store_upsert(self, ltm):
        item_id = await ltm.remember("원본", source="explicit")
        await ltm.remember("업데이트", source="explicit", item_id=item_id)

        recent = await ltm.recent(limit=100)
        matched = [r for r in recent if r.id == item_id]
        assert len(matched) == 1
        assert matched[0].content == "업데이트"

    async def test_clear_all(self, ltm):
        for i in range(3):
            await ltm.remember(f"항목 {i}", source="explicit")
        await ltm.clear()
        assert await ltm.recent() == []


# ── 마이그레이션 멱등성과 backfill ────────────────────────────────────────────

class TestItemStoreMigration:
    async def test_legacy_rows_are_backfilled_and_visible_to_every_user(self, postgres_dsn):
        """범위 컬럼이 없던 테이블에 행이 있을 때, 마이그레이션 후 전역(shared, main) 항목으로 보인다."""
        import asyncpg

        from jarvis.memory import MemoryScope
        from jarvis.memory.manager import MemoryManager
        from jarvis.memory.stores.postgres import PostgresItemStore

        conn = await asyncpg.connect(postgres_dsn)
        try:
            await conn.execute("DROP TABLE IF EXISTS jarvis_ltm_entries")
            await conn.execute("""
                CREATE TABLE jarvis_ltm_entries (
                    id TEXT PRIMARY KEY, content TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'explicit',
                    session_id TEXT, tags JSONB NOT NULL DEFAULT '[]', metadata JSONB NOT NULL DEFAULT '{}',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            await conn.execute(
                "INSERT INTO jarvis_ltm_entries (id, content, source) VALUES "
                "('legacy1', '범위 도입 전 사실', 'explicit'), ('legacy2', '범위 도입 전 요약', 'auto_summary')"
            )
        finally:
            await conn.close()

        for _ in range(2):  # 두 번 열어도(마이그레이션 두 번) 같은 상태
            store = PostgresItemStore(dsn=postgres_dsn)
            memory = MemoryManager(store)
            fact = await memory.get("legacy1")
            summary = await memory.get("legacy2")
            assert fact is not None and summary is not None
            assert (fact.kind.value, fact.visibility, fact.author) == ("semantic", "shared", "user")
            assert fact.scope.user_id is None
            assert (summary.kind.value, summary.author) == ("episodic", "agent")
            assert summary.scope.agent_id == "main"
            # 어느 사용자, 어느 에이전트에서도 보인다
            for scope in (MemoryScope(user_id="u1"), MemoryScope(user_id="u2", agent_id="researcher")):
                assert {i.id for i in await memory.recent(scope=scope, limit=10)} >= {"legacy1", "legacy2"}
            await store.close()

    async def test_scope_filter_in_sql(self, ltm):
        from jarvis.memory import MemoryScope

        await ltm.clear()
        u1 = MemoryScope(user_id="u1", agent_id="main")
        sub = MemoryScope(user_id="u1", agent_id="researcher")
        u2 = MemoryScope(user_id="u2", agent_id="main")
        await ltm.remember("선호 음료: 커피", source="explicit", scope=u1)  # shared
        await ltm.remember("세션 요약: 예산", source="auto_summary", scope=u1)  # private
        await ltm.remember("작업 메모: 논문", source="auto_summary", scope=sub)  # private

        assert {i.content for i in await ltm.recent(scope=u1)} == {"선호 음료: 커피", "세션 요약: 예산"}
        assert {i.content for i in await ltm.recent(scope=sub)} == {"선호 음료: 커피", "작업 메모: 논문"}
        assert await ltm.recent(scope=u2) == []
        assert [i.content for i in await ltm.recall("논문", scope=u1)] == []
        assert [i.content for i in await ltm.recall("논문", scope=sub)] == ["작업 메모: 논문"]

    async def test_supersede_hides_old_fact(self, ltm):
        from jarvis.memory import MemoryScope

        await ltm.clear()
        u1 = MemoryScope(user_id="u1")
        old = await ltm.remember("거주지: 서울", source="explicit", scope=u1)
        new = await ltm.remember("거주지: 부산", source="explicit", scope=u1)
        await ltm.supersede(old, new)
        assert [i.content for i in await ltm.recall("거주지", scope=u1)] == ["거주지: 부산"]
