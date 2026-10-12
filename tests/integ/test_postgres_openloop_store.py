"""PostgresOpenLoopStore 통합: 에이전트 칼럼이 옛 테이블에 멱등하게 붙고, 약속의 에이전트가 저장되어 돌아온다."""

import pytest

pytest.importorskip("testcontainers", reason="testcontainers not installed")
pytest.importorskip("asyncpg", reason="asyncpg not installed")


@pytest.fixture(scope="module")
def postgres_dsn():
    from testcontainers.postgres import PostgresContainer

    try:
        with PostgresContainer("pgvector/pgvector:pg16") as pg:
            yield pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    except Exception as exc:
        pytest.skip(f"Docker unavailable or container failed to start: {exc}")


async def test_agent_column_added_to_old_table_and_round_trips(postgres_dsn):
    import asyncpg

    from jarvis.agent_layer.openloop import OpenLoop, PostgresOpenLoopStore

    conn = await asyncpg.connect(postgres_dsn)
    try:
        await conn.execute("DROP TABLE IF EXISTS jarvis_open_loops")
        await conn.execute("""
            CREATE TABLE jarvis_open_loops (
                id TEXT PRIMARY KEY, description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
                origin_session TEXT, due_ms BIGINT, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
            )
        """)
        await conn.execute(
            "INSERT INTO jarvis_open_loops (id, description, created_at, updated_at) VALUES ('old', '옛 약속', 1, 1)"
        )
    finally:
        await conn.close()

    for _ in range(2):  # 두 번 열어도 같은 상태
        store = PostgresOpenLoopStore(dsn=postgres_dsn)
        await store.add(OpenLoop(id="new", description="뉴스 정리", agent_id="karen"))
        loops = {lp.id: lp.agent_id for lp in await store.list_open()}
        await store.close()
        assert loops == {"old": "main", "new": "karen"}
