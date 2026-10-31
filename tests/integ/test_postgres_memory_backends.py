"""PostgresWorkingStore 와 PostgresItemStore 를 testcontainers 의 실제 PostgreSQL 로 검증한다."""

import pytest

from jarvis.memory.scope import MemoryScope

testcontainers = pytest.importorskip("testcontainers", reason="testcontainers not installed")
pytest.importorskip("asyncpg", reason="asyncpg not installed")

LOCAL = MemoryScope(user_id="local")


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
    from jarvis.model_layer.model_types import UserMessage
    return UserMessage(content=text)


def _asst_msg(text: str):
    from jarvis.model_layer.model_types import AssistantMessage, TextContent, Usage
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
        assert state.notes == [] and state.rehearsal == {}

    async def test_save_load_and_upsert(self, working):
        from jarvis.memory.working import WorkingState
        from jarvis.memory import MemoryScope

        scope = MemoryScope(user_id="u1", agent_id="main", session_id="w1")
        state = WorkingState(scope=scope, rehearsal={"i": 1}, notes=["n"])
        await working.save(state)
        await working.save(state)  # 같은 키 두 번: 행 하나, 같은 상태
        loaded = await working.load(scope)
        assert (loaded.rehearsal, loaded.notes) == ({"i": 1}, ["n"])

        state.notes = ["둘째"]
        await working.save(state)
        assert (await working.load(scope)).notes == ["둘째"]

    async def test_sessions_and_users_are_separate_rows(self, working):
        from jarvis.memory.working import WorkingState
        from jarvis.memory import MemoryScope

        a = MemoryScope(user_id="u1", session_id="iso")
        b = MemoryScope(user_id="u2", session_id="iso")
        await working.save(WorkingState(scope=a, notes=["A"]))
        await working.save(WorkingState(scope=b, notes=["B"]))
        assert (await working.load(a)).notes == ["A"]
        assert (await working.load(b)).notes == ["B"]
        assert (await working.load(a.with_session("other"))).notes == []

    async def test_clear(self, working):
        from jarvis.memory.working import WorkingState
        from jarvis.memory import MemoryScope

        scope = MemoryScope(user_id="u1", session_id="clr")
        await working.save(WorkingState(scope=scope, notes=["x"]))
        await working.clear(scope)
        assert (await working.load(scope)).notes == []

    async def test_close_and_reopen(self, postgres_dsn):
        from jarvis.memory.working.postgres import PostgresWorkingStore
        from jarvis.memory.working import WorkingState
        from jarvis.memory import MemoryScope

        scope = MemoryScope(user_id="u1", session_id="reopen")
        b = PostgresWorkingStore(dsn=postgres_dsn)
        await b.save(WorkingState(scope=scope, notes=["before close"]))
        await b.close()

        b2 = PostgresWorkingStore(dsn=postgres_dsn)
        assert (await b2.load(scope)).notes == ["before close"]
        await b2.close()


# ── PostgresItemStore ────────────────────────────────────────────────────────

class TestPostgresLTM:
    async def test_store_and_get_recent(self, ltm):
        await ltm.remember("Python 배우기", source="explicit", scope=LOCAL)

        recent = await ltm.recent(LOCAL, limit=5)
        contents = [r.content for r in recent]
        assert "Python 배우기" in contents

    async def test_search_keyword(self, ltm):
        await ltm.remember("LangChain 튜토리얼", source="explicit", scope=LOCAL)
        await ltm.remember("Python 기초 문법", source="explicit", scope=LOCAL)

        results = await ltm.recall("LangChain", LOCAL)
        assert any("LangChain" in r.content for r in results)

    async def test_search_case_insensitive(self, ltm):
        await ltm.remember("FastAPI 정리", source="explicit", scope=LOCAL)
        results = await ltm.recall("fastapi", LOCAL)
        assert any("FastAPI" in r.content for r in results)

    async def test_search_no_match(self, ltm):
        await ltm.remember("FastAPI 가이드", source="explicit", scope=LOCAL)
        results = await ltm.recall("Django999", LOCAL)
        assert results == []

    async def test_delete(self, ltm):
        entry_id = await ltm.remember("삭제할 항목", source="explicit", scope=LOCAL)
        await ltm.forget(entry_id)

        recent = await ltm.recent(LOCAL, limit=100)
        assert all(r.id != entry_id for r in recent)

    async def test_store_upsert(self, ltm):
        item_id = await ltm.remember("원본", source="explicit", scope=LOCAL)
        await ltm.remember("업데이트", source="explicit", scope=LOCAL, item_id=item_id)

        recent = await ltm.recent(LOCAL, limit=100)
        matched = [r for r in recent if r.id == item_id]
        assert len(matched) == 1
        assert matched[0].content == "업데이트"

    async def test_clear_all(self, ltm):
        for i in range(3):
            await ltm.remember(f"항목 {i}", source="explicit", scope=LOCAL)
        await ltm.clear()
        assert await ltm.recent(LOCAL) == []


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
            assert (fact.kind.value, fact.author) == ("semantic", "user")
            assert fact.scope.user_id is None
            assert (summary.kind.value, summary.author) == ("episodic", "agent")
            assert summary.scope.agent_id == "main"
            # 어느 사용자의 main 에서도 둘 다 보이고, 다른 에이전트에는 사실만 보인다
            for user in ("u1", "u2"):
                assert {i.id for i in await memory.recent(scope=MemoryScope(user_id=user), limit=10)} >= {
                    "legacy1", "legacy2"
                }
            other = {i.id for i in await memory.recent(scope=MemoryScope(user_id="u1", agent_id="karen"), limit=10)}
            assert "legacy1" in other and "legacy2" not in other
            await store.close()

    async def test_old_columns_are_dropped_and_session_delete_is_exact(self, postgres_dsn):
        """옛 visibility, summary 컬럼은 저장소를 열 때 지운다(두 번 열어도 같다). 세션 삭제는 id 가 같은 행만."""
        import asyncpg

        from jarvis.memory.working.postgres import PostgresWorkingStore
        from jarvis.memory.stores.postgres import PostgresItemStore
        from jarvis.memory.memory_service import MemoryService
        from jarvis.memory import MemoryScope

        conn = await asyncpg.connect(postgres_dsn)
        try:
            await conn.execute("ALTER TABLE jarvis_ltm_entries ADD COLUMN IF NOT EXISTS visibility TEXT")
            await conn.execute("ALTER TABLE jarvis_working_memory ADD COLUMN IF NOT EXISTS summary TEXT")
            await conn.execute(
                "ALTER TABLE jarvis_working_memory ADD COLUMN IF NOT EXISTS summary_covers INTEGER NOT NULL DEFAULT 0"
            )
        finally:
            await conn.close()
        for _ in range(2):
            store, working = PostgresItemStore(dsn=postgres_dsn), PostgresWorkingStore(dsn=postgres_dsn)
            memory = MemoryService(store, working)
            await memory.clear()
            a, b = MemoryScope("u1", "main", "del-s1"), MemoryScope("u1", "main", "del-s10")
            await memory.record_turn(1, "지울 턴", "답", a)
            await memory.record_turn(1, "남을 턴", "답", b)
            await memory.add_note("메모", a)
            await memory.remember("거주지: 부산", source="explicit", scope=a.with_session(None))
            assert await memory.forget_session("del-s1") == (1, 1)
            assert {i.content for i in await memory.recent(scope=a)} == {"사용자: 남을 턴\n답: 답", "거주지: 부산"}
            await store.close()
            await working.close()
        conn = await asyncpg.connect(postgres_dsn)
        try:
            cols = {r["column_name"] for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name IN ('jarvis_ltm_entries', 'jarvis_working_memory')"
            )}
        finally:
            await conn.close()
        assert not cols & {"visibility", "summary", "summary_covers"}

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

    async def test_layer_policy_in_sql(self, postgres_dsn):
        """SQL 이 정책을 강제한다: 허락받은 에이전트만 남의 EDM, PDM 을 읽고, shared 표시는 열쇠가 아니다."""
        from jarvis.memory.access import MemoryPolicy, MemoryReadPolicy
        from jarvis.memory.stores.postgres import PostgresItemStore
        from jarvis.memory.memory_service import MemoryService
        from jarvis.memory import MemoryKind, MemoryScope

        store = PostgresItemStore(dsn=postgres_dsn)
        policies = {"karen": MemoryPolicy(read=MemoryReadPolicy(edm=["main"]))}
        memory = MemoryService(store, policies=policies)
        try:
            await memory.clear()
            main, karen = MemoryScope(user_id="u1", agent_id="main"), MemoryScope(user_id="u1", agent_id="karen")
            await memory.remember("공고 작업: 분양가 표", source="session_end", scope=main)
            await memory.remember("공고 작업 절차", source="eval", scope=main, kind=MemoryKind.PROCEDURAL)
            await memory.remember("공고 작업: 공유 결과", source="promoted", scope=karen)
            await memory.remember("관심 지역: 서울", source="explicit", scope=karen)

            assert {i.content for i in await memory.recent(scope=karen)} == {
                "공고 작업: 분양가 표", "공고 작업: 공유 결과", "관심 지역: 서울"
            }
            assert {i.content for i in await memory.recent(scope=main)} == {
                "공고 작업: 분양가 표", "공고 작업 절차", "관심 지역: 서울"
            }
            assert {i.content for i in await memory.recall("공고 작업", karen)} == {
                "공고 작업: 분양가 표", "공고 작업: 공유 결과"
            }
        finally:
            await store.close()

    async def test_item_filter_in_sql(self, postgres_dsn):
        """사고 로그 제외와 일화 조건(작업 종류, 성패, 기간)을 SQL 이 건다. 후보를 자르기 전에 거른다."""
        from datetime import datetime

        from jarvis.memory.stores.postgres import PostgresItemStore
        from jarvis.memory.memory_service import MemoryService
        from jarvis.memory import MemoryScope

        store = PostgresItemStore(dsn=postgres_dsn)
        memory = MemoryService(store, stm_turns=3)
        scope = MemoryScope(user_id="u1", agent_id="main", session_id="s1")
        try:
            await memory.clear()
            for index, failed, day in ((1, False, "2026-10-01"), (2, True, "2026-10-05")):
                item_id = await memory.record_turn(
                    index, f"대출 계산 {index}", "답", scope, task_type="housing_loan", failed=failed
                )
                item = await memory.get(item_id)
                assert item is not None
                item.occurred_at = datetime.fromisoformat(day)
                await store.store(item)
            await memory.remember("대출 계산 사고", source="thought", scope=scope)

            got = await memory.recall_episodes("대출 계산", scope)
            assert {i.content for i in got} == {"사용자: 대출 계산 1\n답: 답", "사용자: 대출 계산 2\n답: 답"}
            failed_only = await memory.recall_episodes("대출 계산", scope, outcome="failure")
            assert [i.metadata["turn"] for i in failed_only] == [2]
            dated = await memory.recall_episodes(
                "대출 계산", scope, since=datetime(2026, 10, 1), until=datetime(2026, 10, 2)
            )
            assert [i.metadata["turn"] for i in dated] == [1]
            assert await memory.recall_episodes("대출 계산", scope, task_type="weather") == []

            # 정제 후보: 같은 종류 성공이 셋이어야 한다. 실패한 턴 2 와 사고 로그는 세지 않는다
            await memory.record_turn(3, "대출 계산 3", "답", scope, task_type="housing_loan")
            assert await memory.refinement_candidates(scope) == []
            await memory.record_turn(4, "대출 계산 4", "답", scope, task_type="housing_loan")
            [candidate] = await memory.refinement_candidates(scope)
            assert candidate.task_type == "housing_loan"
            assert sorted(i.metadata["turn"] for i in candidate.evidence) == [1, 3, 4]
        finally:
            await store.close()

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
