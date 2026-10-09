"""PostgresWorkingStore + PostgresItemStore 통합 테스트.

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
        with PostgresContainer("pgvector/pgvector:pg16") as pg:
            dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
            yield dsn
    except Exception as exc:
        pytest.skip(f"Docker unavailable or container failed to start: {exc}")


@pytest.fixture
async def working(postgres_dsn: str):
    from jarvis.memory.working.postgres import PostgresWorkingStore

    b = PostgresWorkingStore(dsn=postgres_dsn)
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


# ── PostgresWorkingStore ──────────────────────────────────────────────────────

class TestPostgresWorkingStore:
    async def test_load_empty(self, working):
        from jarvis.memory import MemoryScope

        state = await working.load(MemoryScope(user_id="u1", session_id="nothing-here"))
        assert state.summary is None and state.summary_covers == 0 and state.notes == []

    async def test_save_load_and_upsert(self, working):
        from jarvis.memory import MemoryScope
        from jarvis.memory.working import WorkingState

        scope = MemoryScope(user_id="u1", agent_id="main", session_id="w1")
        state = WorkingState(scope=scope, summary="첫 요약", summary_covers=3, rehearsal={"i": 1}, notes=["n"])
        await working.save(state)
        await working.save(state)  # 같은 키 두 번: 행 하나, 같은 상태
        loaded = await working.load(scope)
        assert (loaded.summary, loaded.summary_covers) == ("첫 요약", 3)
        assert (loaded.rehearsal, loaded.notes) == ({"i": 1}, ["n"])

        state.summary, state.summary_covers = "둘째 요약", 7
        await working.save(state)
        assert (await working.load(scope)).summary == "둘째 요약"

    async def test_sessions_and_users_are_separate_rows(self, working):
        from jarvis.memory import MemoryScope
        from jarvis.memory.working import WorkingState

        a = MemoryScope(user_id="u1", session_id="iso")
        b = MemoryScope(user_id="u2", session_id="iso")
        await working.save(WorkingState(scope=a, summary="A"))
        await working.save(WorkingState(scope=b, summary="B"))
        assert (await working.load(a)).summary == "A"
        assert (await working.load(b)).summary == "B"
        assert (await working.load(a.with_session("other"))).summary is None

    async def test_clear(self, working):
        from jarvis.memory import MemoryScope
        from jarvis.memory.working import WorkingState

        scope = MemoryScope(user_id="u1", session_id="clr")
        await working.save(WorkingState(scope=scope, summary="x"))
        await working.clear(scope)
        assert (await working.load(scope)).summary is None

    async def test_close_and_reopen(self, postgres_dsn):
        from jarvis.memory import MemoryScope
        from jarvis.memory.working import WorkingState
        from jarvis.memory.working.postgres import PostgresWorkingStore

        scope = MemoryScope(user_id="u1", session_id="reopen")
        b = PostgresWorkingStore(dsn=postgres_dsn)
        await b.save(WorkingState(scope=scope, summary="before close", summary_covers=2))
        await b.close()

        b2 = PostgresWorkingStore(dsn=postgres_dsn)
        assert (await b2.load(scope)).summary == "before close"
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


# ── pgvector ─────────────────────────────────────────────────────────────────

class TestPgvector:
    async def test_vector_search_finds_paraphrase_and_survives_reopen(self, postgres_dsn):
        from jarvis.memory import MemoryScope
        from jarvis.memory.eval.fake_embedder import FakeEmbedder
        from jarvis.memory.manager import MemoryManager
        from jarvis.memory.stores.postgres import PostgresItemStore

        scope = MemoryScope(user_id="vec", agent_id="main")
        store = PostgresItemStore(dsn=postgres_dsn, dimensions=FakeEmbedder.dimensions)
        memory = MemoryManager(store, embedder=FakeEmbedder())
        await memory.clear(scope)
        item_id = await memory.remember("거주지: 부산", source="explicit", scope=scope)
        assert store.vector_enabled

        stored = await memory.get(item_id)
        assert stored.embedding is not None and len(stored.embedding) == FakeEmbedder.dimensions
        assert [i.content for i in await memory.recall("사는 곳", scope=scope)] == ["거주지: 부산"]  # 키워드 불일치
        assert await memory.recall("자동차 번호", scope=scope) == []
        await store.close()

        store2 = PostgresItemStore(dsn=postgres_dsn, dimensions=FakeEmbedder.dimensions)  # 마이그레이션 두 번째
        memory2 = MemoryManager(store2, embedder=FakeEmbedder())
        assert [i.content for i in await memory2.recall("사는 곳", scope=scope)] == ["거주지: 부산"]
        assert await memory2.reembed(scope) == 0  # 같은 모델이면 할 일 없음
        await store2.close()

    async def test_store_without_dimensions_keeps_keyword_search(self, ltm):
        from jarvis.memory import MemoryScope

        scope = MemoryScope(user_id="kw", agent_id="main")
        await ltm.clear(scope)
        await ltm.remember("거주지: 부산", source="explicit", scope=scope)
        assert ltm.store.vector_enabled is False
        assert [i.content for i in await ltm.recall("거주지", scope=scope)] == ["거주지: 부산"]
