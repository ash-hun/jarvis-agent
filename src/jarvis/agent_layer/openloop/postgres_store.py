"""[agent_layer] open-loop 을 PostgreSQL 테이블에 영속한다(asyncpg 풀, 상태 변경은 UPDATE)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from jarvis.agent_layer.openloop.store import OpenLoopStore
from jarvis.agent_layer.openloop.types import LOOP_STATUSES, OpenLoop
from jarvis.memory.scope import MAIN_AGENT
from jarvis.model_layer.embeddings import Embedder


class PostgresOpenLoopStore(OpenLoopStore):
    """PostgreSQL 기반 open-loop 저장소 (docker/외부 DB 영속). asyncpg 풀 패턴.

    PostgresLTMBackend와 동일한 풀/테이블 초기화 패턴. 상태 변경은 UPDATE.
    기본 클래스의 메모리 저장은 쓰지 않고 모든 메서드를 DB 질의로 재정의한다.
    """

    def __init__(self, dsn: str, embedder: Embedder | None = None) -> None:
        super().__init__(embedder)
        self._dsn = dsn
        # asyncpg 는 타입 스텁이 없어 풀과 레코드를 Any 로 다룬다
        self._pool: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def _get_pool(self) -> Any:
        import asyncpg as _asyncpg

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if self._pool is None or self._loop is not current_loop:
            self._pool = await _asyncpg.create_pool(self._dsn)
            self._loop = current_loop
            await self._ensure_tables()
        return self._pool

    async def _ensure_tables(self) -> None:
        pool = self._pool
        assert pool
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS jarvis_open_loops (
                    id              TEXT   PRIMARY KEY,
                    description     TEXT   NOT NULL,
                    status          TEXT   NOT NULL DEFAULT 'open',
                    origin_session  TEXT,
                    due_ms          BIGINT,
                    created_at      BIGINT NOT NULL,
                    updated_at      BIGINT NOT NULL
                )
            """)
            # 최상위 에이전트 도입 전 약속은 전부 main 의 것이다
            await conn.execute(
                f"ALTER TABLE jarvis_open_loops ADD COLUMN IF NOT EXISTS agent_id TEXT NOT NULL DEFAULT '{MAIN_AGENT}'"
            )
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_openloop_status
                ON jarvis_open_loops(status, created_at DESC)
            """)

    async def add(self, loop: OpenLoop) -> str:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO jarvis_open_loops
                    (id, description, status, origin_session, due_ms, created_at, updated_at, agent_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (id) DO UPDATE SET
                    description    = EXCLUDED.description,
                    status         = EXCLUDED.status,
                    origin_session = EXCLUDED.origin_session,
                    due_ms         = EXCLUDED.due_ms,
                    updated_at     = EXCLUDED.updated_at,
                    agent_id       = EXCLUDED.agent_id
                """,
                loop.id,
                loop.description,
                loop.status,
                loop.origin_session,
                loop.due_ms,
                loop.created_at,
                loop.updated_at,
                loop.agent_id,
            )
        return loop.id

    async def _open_in_session(self, session_id: str | None) -> list[OpenLoop]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # 판정은 파이썬 merge_loop 한 곳에서. 세션당 열린 약속은 몇 건이라 다 가져와도 싸다
            rows = await conn.fetch(
                "SELECT * FROM jarvis_open_loops"
                " WHERE status = 'open' AND origin_session IS NOT DISTINCT FROM $1",
                session_id,
            )
        return [_row_to_loop(r) for r in rows]

    async def list_open(self, session_id: str | None = None, limit: int = 20) -> list[OpenLoop]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if session_id is None:
                rows = await conn.fetch(
                    "SELECT * FROM jarvis_open_loops WHERE status = 'open'"
                    " ORDER BY created_at DESC LIMIT $1",
                    limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM jarvis_open_loops WHERE status = 'open'"
                    " AND origin_session = $1 ORDER BY created_at DESC LIMIT $2",
                    session_id,
                    limit,
                )
        return [_row_to_loop(r) for r in rows]

    async def get(self, loop_id: str) -> OpenLoop | None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM jarvis_open_loops WHERE id = $1", loop_id)
        return _row_to_loop(row) if row is not None else None

    async def update_status(self, loop_id: str, status: str) -> bool:
        if status not in LOOP_STATUSES:
            return False
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            result: str = await conn.execute(
                "UPDATE jarvis_open_loops SET status = $2, updated_at = $3 WHERE id = $1",
                loop_id,
                status,
                int(time.time() * 1000),
            )
        return result.endswith(" 1")  # "UPDATE 1" → 성공

    async def all(self) -> list[OpenLoop]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM jarvis_open_loops")
        return [_row_to_loop(r) for r in rows]

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._loop = None


def _row_to_loop(row: Any) -> OpenLoop:
    return OpenLoop(
        id=row["id"],
        description=row["description"],
        status=row["status"],
        origin_session=row["origin_session"],
        agent_id=row["agent_id"],
        due_ms=row["due_ms"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
