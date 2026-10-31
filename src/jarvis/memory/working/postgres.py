"""[memory] (user, agent, session) 당 한 행을 upsert 하는 PostgreSQL 작업 기억 저장소."""

import json
import asyncio
from typing import Any
from datetime import UTC, datetime

from jarvis.memory.working.state import WorkingState, WorkingStore
from jarvis.memory.scope import LOCAL_USER, MemoryScope
from jarvis.memory.stores.postgres import like_prefix

TABLE = "jarvis_working_memory"


class PostgresWorkingStore(WorkingStore):
    def __init__(self, dsn: str) -> None:
        super().__init__()
        self._dsn = dsn
        self._pool: Any = None  # asyncpg 는 스텁이 없어 Pool 타입을 쓸 수 없다
        self._loop: asyncio.AbstractEventLoop | None = None

    async def _get_pool(self) -> Any:
        import asyncpg

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if self._pool is None or self._loop is not current_loop:
            self._pool = await asyncpg.create_pool(self._dsn)
            self._loop = current_loop
            async with self._pool.acquire() as conn:
                await conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {TABLE} (
                        user_id        TEXT        NOT NULL,
                        agent_id       TEXT        NOT NULL,
                        session_id     TEXT        NOT NULL,
                        rehearsal      JSONB       NOT NULL DEFAULT '{{}}',
                        notes          JSONB       NOT NULL DEFAULT '[]',
                        updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                        PRIMARY KEY (user_id, agent_id, session_id)
                    )
                """)
        return self._pool

    async def load(self, scope: MemoryScope) -> WorkingState:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT rehearsal, notes, updated_at FROM {TABLE}"
                " WHERE user_id = $1 AND agent_id = $2 AND session_id = $3",
                *_key(scope),
            )
        if row is None:
            return WorkingState(scope=scope)
        rehearsal, notes = row["rehearsal"], row["notes"]
        updated = row["updated_at"]
        if updated.tzinfo is not None:
            updated = updated.astimezone(UTC).replace(tzinfo=None)
        return WorkingState(
            scope=scope,
            rehearsal=json.loads(rehearsal) if isinstance(rehearsal, str) else dict(rehearsal or {}),
            notes=json.loads(notes) if isinstance(notes, str) else list(notes or []),
            updated_at=updated,
        )

    async def save(self, state: WorkingState) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {TABLE}
                    (user_id, agent_id, session_id, rehearsal, notes, updated_at)
                VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6)
                ON CONFLICT (user_id, agent_id, session_id) DO UPDATE SET
                    rehearsal = EXCLUDED.rehearsal, notes = EXCLUDED.notes, updated_at = EXCLUDED.updated_at
                """,
                *_key(state.scope),
                json.dumps(state.rehearsal, ensure_ascii=False),
                json.dumps(state.notes, ensure_ascii=False),
                datetime.now(),
            )

    async def clear(self, scope: MemoryScope) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"DELETE FROM {TABLE} WHERE user_id = $1 AND agent_id = $2 AND session_id = $3", *_key(scope)
            )

    async def delete_sessions(self, prefixes: tuple[str, ...], dry_run: bool = False) -> int:
        if not prefixes:
            return 0
        patterns = [like_prefix(p) for p in prefixes]
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if dry_run:
                return int(await conn.fetchval(f"SELECT count(*) FROM {TABLE} WHERE session_id LIKE ANY($1)", patterns))
            status = await conn.execute(f"DELETE FROM {TABLE} WHERE session_id LIKE ANY($1)", patterns)
        return int(status.split()[-1])

    async def legacy_stm_rows(self) -> int | None:
        """범위 도입 전 STM 메시지 테이블의 행 수. 테이블이 없으면 None."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            exists = await conn.fetchval("SELECT to_regclass('jarvis_stm_messages') IS NOT NULL")
            if not exists:
                return None
            return int(await conn.fetchval("SELECT count(*) FROM jarvis_stm_messages"))

    async def drop_legacy_stm(self) -> None:
        """옛 STM 테이블 삭제. 두 번 불러도 같은 상태(IF EXISTS)."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS jarvis_stm_messages")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._loop = None


def _key(scope: MemoryScope) -> tuple[str, str, str]:
    return scope.user_id or LOCAL_USER, scope.agent_id, scope.session_id or "default"
