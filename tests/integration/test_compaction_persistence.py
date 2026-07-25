"""CompactionMiddleware → Postgres LTM 영속성 통합 테스트.

unit 레벨(test_episodic.py)은 in-memory LTM으로 compaction→저장을 검증한다.
여기서는 실제 PostgreSQL에 자동 요약이 **안착하고 백엔드 재기동 후에도 생존**하는지
(장기 세션 내구성)를 testcontainers로 검증한다. Docker/testcontainers 없으면 자동 skip.
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
async def ltm(postgres_dsn: str):
    from jarvis.agent_layer.memory.backends.postgres_ltm import PostgresLTMBackend

    b = PostgresLTMBackend(dsn=postgres_dsn)
    await b.clear_all()  # 모듈 내 테스트 간 격리
    yield b
    await b.close()


def _user_msg(text: str):
    from jarvis.model_layer.types import UserMessage

    return UserMessage(content=text)


# ── Compaction → Postgres LTM 영속성 ──────────────────────────────────────────


class TestCompactionPersistence:
    async def test_summary_persists_to_postgres(self, faux_model_with_response, ltm):
        """임계값 초과 → 자동 요약이 Postgres LTM에 source=auto_summary로 저장된다."""
        from jarvis.agent_layer.memory.compaction import CompactionMiddleware

        model = faux_model_with_response("압축 요약: 사용자는 Python과 FastAPI를 다뤘다.")
        middleware = CompactionMiddleware(
            model=model,
            threshold_chars=10,  # 강제 압축
            keep_recent=1,
            ltm_backend=ltm,
        )
        msgs = [_user_msg("첫 번째"), _user_msg("두 번째"), _user_msg("세 번째")]
        result = await middleware.transform(msgs, {"session_id": "pg-compact"})

        # 반환은 [요약 메시지] + keep_recent
        assert len(result) == 2
        assert "Compacted context summary" in (result[0].content if isinstance(result[0].content, str) else "")

        recent = await ltm.get_recent(limit=10)
        summaries = [r for r in recent if r.source == "auto_summary"]
        assert len(summaries) == 1
        assert summaries[0].session_id == "pg-compact"
        assert "Python" in summaries[0].content

    async def test_summary_survives_backend_reopen(self, faux_model_with_response, postgres_dsn):
        """백엔드를 닫았다 새로 열어도 자동 요약이 살아있다(실 내구성)."""
        from jarvis.agent_layer.memory.backends.postgres_ltm import PostgresLTMBackend
        from jarvis.agent_layer.memory.compaction import CompactionMiddleware

        b1 = PostgresLTMBackend(dsn=postgres_dsn)
        await b1.clear_all()
        middleware = CompactionMiddleware(
            model=faux_model_with_response("요약: 재기동 후에도 보존되어야 한다."),
            threshold_chars=10,
            keep_recent=1,
            ltm_backend=b1,
        )
        await middleware.transform(
            [_user_msg("a"), _user_msg("b"), _user_msg("c")],
            {"session_id": "pg-durable"},
        )
        await b1.close()

        # 완전히 새 백엔드 인스턴스로 재조회
        b2 = PostgresLTMBackend(dsn=postgres_dsn)
        recent = await b2.get_recent(limit=10)
        await b2.close()

        durable = [r for r in recent if r.session_id == "pg-durable" and r.source == "auto_summary"]
        assert len(durable) == 1
        assert "보존" in durable[0].content

    async def test_below_threshold_writes_nothing(self, faux_model_with_response, ltm):
        """임계값 이하면 요약·LTM 저장이 발생하지 않는다."""
        from jarvis.agent_layer.memory.compaction import CompactionMiddleware

        middleware = CompactionMiddleware(
            model=faux_model_with_response("불려선 안 됨"),
            threshold_chars=10_000_000,  # 사실상 도달 불가
            keep_recent=1,
            ltm_backend=ltm,
        )
        original = [_user_msg("짧음")]
        result = await middleware.transform(original, {"session_id": "pg-noop"})

        assert result == original  # 변형 없이 그대로 통과
        assert await ltm.get_recent(limit=10) == []
