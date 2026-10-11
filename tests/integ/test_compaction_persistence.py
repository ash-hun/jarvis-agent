"""컴팩션 → Postgres 영속성 통합 테스트.

unit 레벨(test_memory_working.py)은 in-memory 저장소로 observe 의 동작을 검증한다.
여기서는 실제 PostgreSQL 에 요약이 안착하고, 백엔드를 다시 열어도 재요약 없이 이어지는지 본다.
Docker/testcontainers 없으면 자동 skip.
"""

from __future__ import annotations

import pytest

testcontainers = pytest.importorskip("testcontainers", reason="testcontainers not installed")
pytest.importorskip("asyncpg", reason="asyncpg not installed")

CTX = {"session_id": "pg-compact", "user_id": "u1", "agent_id": "main"}


@pytest.fixture(scope="module")
def postgres_dsn():
    from testcontainers.postgres import PostgresContainer

    try:
        with PostgresContainer("pgvector/pgvector:pg16") as pg:
            dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
            yield dsn
    except Exception as exc:
        pytest.skip(f"Docker unavailable or container failed to start: {exc}")


def _user_msg(text: str):
    from jarvis.model_layer.types import UserMessage

    return UserMessage(content=text)


def _manager(dsn: str, model, threshold: int):
    from jarvis.memory.consolidation import llm_summarizer
    from jarvis.memory.memory_service import MemoryService
    from jarvis.memory.stores.postgres import PostgresItemStore
    from jarvis.memory.working.postgres import PostgresWorkingStore

    store, working = PostgresItemStore(dsn=dsn), PostgresWorkingStore(dsn=dsn)
    manager = MemoryService(store, working, summarizer=llm_summarizer(model), threshold_chars=threshold, keep_recent=1)
    return manager, store, working


class TestCompactionPersistence:
    async def test_summary_persists_and_second_turn_does_not_resummarize(self, faux_model_with_response, postgres_dsn):
        from jarvis.memory import MemoryScope
        from jarvis.memory.eval.probe import count_llm_calls

        model = faux_model_with_response("압축 요약: 사용자는 Python과 FastAPI를 다뤘다.")
        memory, store, working = _manager(postgres_dsn, model, threshold=10)
        scope = MemoryScope(user_id="u1", agent_id="main", session_id="pg-compact")
        await store.clear()
        await working.clear(scope)

        history = [_user_msg("첫 번째"), _user_msg("두 번째"), _user_msg("세 번째")]
        with count_llm_calls("faux") as c:
            result = await memory.observe(history, CTX)
        assert c.calls == 1 and len(result) == 2 and "Compacted context summary" in result[0].content

        summaries = [r for r in await memory.recent(scope=scope, limit=10) if r.source == "auto_summary"]
        assert len(summaries) == 1 and summaries[0].session_id == "pg-compact" and "Python" in summaries[0].content

        # 완전히 새 인스턴스로 다음 턴: 요약은 DB 에서 읽히고 임계를 다시 넘기 전엔 재요약하지 않는다
        await store.close()
        await working.close()
        memory2, store2, working2 = _manager(postgres_dsn, faux_model_with_response("불려선 안 됨"), threshold=10_000)
        with count_llm_calls("faux") as c:
            result2 = await memory2.observe(history + [_user_msg("네 번째")], CTX)
        assert c.calls == 0
        assert "압축 요약" in result2[0].content and result2[-1].content == "네 번째"
        await store2.close()
        await working2.close()

    async def test_below_threshold_writes_nothing(self, faux_model_with_response, postgres_dsn):
        from jarvis.memory import MemoryScope

        memory, store, working = _manager(postgres_dsn, faux_model_with_response("불려선 안 됨"), threshold=10_000_000)
        scope = MemoryScope(user_id="u1", agent_id="main", session_id="pg-noop")
        await store.clear()
        original = [_user_msg("짧음")]
        assert await memory.observe(original, {**CTX, "session_id": "pg-noop"}) == original
        assert await memory.recent(scope=scope, limit=10) == []
        await store.close()
        await working.close()
