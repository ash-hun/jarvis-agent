"""PostgresWorkingStore 와 PostgresItemStore 를 testcontainers 의 실제 PostgreSQL 로 검증한다."""

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
    from jarvis.memory.stores.postgres import PostgresItemStore
    from jarvis.memory.memory_service import MemoryService

    store = PostgresItemStore(dsn=postgres_dsn)
    yield MemoryService(store)
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
        from jarvis.memory.working import WorkingState
        from jarvis.memory import MemoryScope

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
        from jarvis.memory.working import WorkingState
        from jarvis.memory import MemoryScope

        a = MemoryScope(user_id="u1", session_id="iso")
        b = MemoryScope(user_id="u2", session_id="iso")
        await working.save(WorkingState(scope=a, summary="A"))
        await working.save(WorkingState(scope=b, summary="B"))
        assert (await working.load(a)).summary == "A"
        assert (await working.load(b)).summary == "B"
        assert (await working.load(a.with_session("other"))).summary is None

    async def test_clear(self, working):
        from jarvis.memory.working import WorkingState
        from jarvis.memory import MemoryScope

        scope = MemoryScope(user_id="u1", session_id="clr")
        await working.save(WorkingState(scope=scope, summary="x"))
        await working.clear(scope)
        assert (await working.load(scope)).summary is None

    async def test_close_and_reopen(self, postgres_dsn):
        from jarvis.memory.working.postgres import PostgresWorkingStore
        from jarvis.memory.working import WorkingState
        from jarvis.memory import MemoryScope

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
        """범위 컬럼이 없던 테이블의 행은 전역 main 항목이 된다. 사실은 모든 에이전트에, 일화는 main 에만 보인다."""
        import asyncpg

        from jarvis.memory.stores.postgres import PostgresItemStore
        from jarvis.memory.memory_service import MemoryService
        from jarvis.memory import MemoryScope

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
            memory = MemoryService(store)
            fact = await memory.get("legacy1")
            summary = await memory.get("legacy2")
            assert fact is not None and summary is not None
            assert (fact.kind.value, fact.visibility, fact.author) == ("semantic", "shared", "user")
            assert fact.scope.user_id is None
            assert (summary.kind.value, summary.visibility, summary.author) == ("episodic", "private", "agent")
            assert summary.scope.agent_id == "main"
            # 어느 사용자의 main 에서도 둘 다 보이고, 다른 에이전트에는 사실만 보인다
            for user in ("u1", "u2"):
                assert {i.id for i in await memory.recent(scope=MemoryScope(user_id=user), limit=10)} >= {
                    "legacy1", "legacy2"
                }
            other = {i.id for i in await memory.recent(scope=MemoryScope(user_id="u1", agent_id="karen"), limit=10)}
            assert "legacy1" in other and "legacy2" not in other
            await store.close()

    async def test_shared_episodes_from_old_backfill_become_private(self, postgres_dsn):
        """예전 backfill 이 shared 로 둔 일화는 main 전용으로 바뀌고, 사실은 그대로 shared 다. 두 번 열어도 같다."""
        import asyncpg

        from jarvis.memory.stores.postgres import PostgresItemStore

        store = PostgresItemStore(dsn=postgres_dsn)
        await store._get_pool()  # 테이블 준비
        await store.close()
        conn = await asyncpg.connect(postgres_dsn)
        try:
            await conn.execute("DELETE FROM jarvis_ltm_entries")
            await conn.execute(
                "INSERT INTO jarvis_ltm_entries (id, content, source, kind, visibility, agent_id, author) VALUES "
                "('ep', '옛 요약', 'auto_summary', 'episodic', 'shared', 'main', 'agent'),"
                "('fa', '옛 사실', 'explicit', 'semantic', 'shared', 'main', 'user')"
            )
        finally:
            await conn.close()

        for _ in range(2):
            store = PostgresItemStore(dsn=postgres_dsn)
            await store._get_pool()
            await store.close()
        conn = await asyncpg.connect(postgres_dsn)
        try:
            rows = dict(await conn.fetch("SELECT id, visibility FROM jarvis_ltm_entries ORDER BY id"))
        finally:
            await conn.close()
        assert rows == {"ep": "private", "fa": "shared"}

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
        from jarvis.memory.stores.postgres import PostgresItemStore
        from jarvis.memory.eval.fake_embedder import FakeEmbedder
        from jarvis.memory.memory_service import MemoryService
        from jarvis.memory import MemoryScope

        scope = MemoryScope(user_id="vec", agent_id="main")
        store = PostgresItemStore(dsn=postgres_dsn, dimensions=FakeEmbedder.dimensions)
        memory = MemoryService(store, embedder=FakeEmbedder())
        await memory.clear(scope)
        item_id = await memory.remember("거주지: 부산", source="explicit", scope=scope)
        assert store.vector_enabled

        stored = await memory.get(item_id)
        assert stored.embedding is not None and len(stored.embedding) == FakeEmbedder.dimensions
        assert [i.content for i in await memory.recall("사는 곳", scope=scope)] == ["거주지: 부산"]  # 키워드 불일치
        assert await memory.recall("자동차 번호", scope=scope) == []
        await store.close()

        store2 = PostgresItemStore(dsn=postgres_dsn, dimensions=FakeEmbedder.dimensions)  # 마이그레이션 두 번째
        memory2 = MemoryService(store2, embedder=FakeEmbedder())
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


class TestLegacyStmCleanup:
    async def test_report_and_drop_are_idempotent(self, postgres_dsn):
        import asyncpg

        from jarvis.memory.working.postgres import PostgresWorkingStore

        conn = await asyncpg.connect(postgres_dsn)
        try:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS jarvis_stm_messages (id SERIAL PRIMARY KEY, session_id TEXT)"
            )
            await conn.execute("INSERT INTO jarvis_stm_messages (session_id) VALUES ('a'), ('b')")
        finally:
            await conn.close()

        store = PostgresWorkingStore(dsn=postgres_dsn)
        assert await store.legacy_stm_rows() == 2
        await store.drop_legacy_stm()
        await store.drop_legacy_stm()  # 두 번째도 에러 없이
        assert await store.legacy_stm_rows() is None
        await store.close()


class TestPostgresTaskPatterns:
    """작업 패턴이 Postgres 에서도 에이전트 전용이고, 같은 이름은 한 행으로 덮인다."""

    async def test_patterns_are_per_agent_and_upserted(self, ltm):
        from jarvis.memory.long_term.task_pattern import TaskPattern
        from jarvis.memory.scope import MemoryScope

        karen = MemoryScope(user_id="pg-u", agent_id="karen", session_id="k1")
        main = MemoryScope(user_id="pg-u", agent_id="main", session_id="m1")
        pattern = TaskPattern("예산 추천", "예산 요청", "대출 = 금액 - 현금", ("예산", "현금"))
        await ltm.remember_pattern(pattern, karen)
        await ltm.remember_pattern(TaskPattern("예산 추천", "예산 요청", "금리 3.5%", ("예산",)), karen)

        assert [p.steps for p in await ltm.task_patterns(karen)] == ["금리 3.5%"]
        assert await ltm.task_patterns(main) == []
        assert await ltm.forget_pattern("예산 추천", karen)
        assert await ltm.task_patterns(karen) == []


# ── 회상 후보(최신, 중요도, 거리 합집합)와 가리킨 대화 ─────────────────────────

class TestRecallCandidates:
    async def test_old_salient_episode_and_old_core_fact_survive_newer_rows(self, postgres_dsn):
        from datetime import datetime, timedelta

        from jarvis.memory.stores.postgres import PostgresItemStore
        from jarvis.memory.eval.fake_embedder import FakeEmbedder
        from jarvis.memory.memory_service import MemoryService
        from jarvis.memory import MemoryKind, MemoryScope

        scope = MemoryScope(user_id="cand", agent_id="main")
        now = datetime.now()
        store = PostgresItemStore(dsn=postgres_dsn, dimensions=FakeEmbedder.dimensions)
        memory = MemoryService(store, embedder=FakeEmbedder(), fixed_facts=3)
        await memory.remember("여행: 응급실에 실려 갔다", source="session_end", scope=scope, importance=1.0,
                              created_at=now - timedelta(days=200))
        await memory.remember("이름: 재훈", source="explicit", scope=scope, created_at=now - timedelta(days=200))
        for i in range(15):
            await memory.remember(f"여행: 사진 {i}", source="session_end", scope=scope, importance=0.1,
                                  created_at=now - timedelta(hours=i))
            await memory.remember(f"취향{i}: 사소함", source="extracted", scope=scope, importance=0.3,
                                  created_at=now - timedelta(hours=i))

        recalled = await memory.recall("여행", scope, kinds=[MemoryKind.EPISODIC], limit=3)
        assert any("응급실" in i.content for i in recalled)
        assert any("재훈" in i.content for i in await memory.fixed_facts(scope))
        await store.close()

    async def test_referent_is_searchable_by_keyword(self, ltm):
        from jarvis.memory import MemoryScope

        scope = MemoryScope(user_id="ref", agent_id="main")
        await ltm.remember("그 방법 계속 써", source="explicit", scope=scope, referent="롤백 방식으로 고쳤다")
        assert [i.content for i in await ltm.recall("롤백", scope)] == ["그 방법 계속 써"]
