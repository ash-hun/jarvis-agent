from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from jarvis.agent_layer.memory.backends.protocol import MemoryEntry


class PostgresLTMBackend:
    """PostgreSQL 기반 장기 메모리 백엔드. ILIKE 키워드 검색. asyncpg 풀 패턴."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
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
                CREATE TABLE IF NOT EXISTS jarvis_ltm_entries (
                    id          TEXT        PRIMARY KEY,
                    content     TEXT        NOT NULL,
                    source      TEXT        NOT NULL DEFAULT 'explicit',
                    session_id  TEXT,
                    tags        JSONB       NOT NULL DEFAULT '[]',
                    metadata    JSONB       NOT NULL DEFAULT '{}',
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ltm_created
                ON jarvis_ltm_entries(created_at DESC)
            """)

    async def store(self, entry: MemoryEntry) -> str:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO jarvis_ltm_entries
                    (id, content, source, session_id, tags, metadata, created_at)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7)
                ON CONFLICT (id) DO UPDATE SET
                    content    = EXCLUDED.content,
                    source     = EXCLUDED.source,
                    session_id = EXCLUDED.session_id,
                    tags       = EXCLUDED.tags,
                    metadata   = EXCLUDED.metadata,
                    created_at = EXCLUDED.created_at
                """,
                entry.id,
                entry.content,
                entry.source,
                entry.session_id,
                json.dumps(entry.tags, ensure_ascii=False),
                json.dumps(entry.metadata, ensure_ascii=False),
                entry.created_at,
            )
        return entry.id

    async def search(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        """토큰 단위 OR 검색 — 각 토큰을 ILIKE로 연결 (대소문자 무관)."""
        tokens = [t for t in query.split() if t]
        if not tokens:
            return []

        clauses = " OR ".join(f"content ILIKE ${i + 1}" for i in range(len(tokens)))
        params: list = [f"%{t}%" for t in tokens] + [limit]
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT id, content, source, session_id, tags, metadata, created_at"
                f" FROM jarvis_ltm_entries WHERE {clauses}"
                f" ORDER BY created_at DESC LIMIT ${len(tokens) + 1}",
                *params,
            )
        return [_row_to_entry(row) for row in rows]

    async def get_recent(self, limit: int = 10) -> list[MemoryEntry]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, content, source, session_id, tags, metadata, created_at"
                " FROM jarvis_ltm_entries ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        return [_row_to_entry(row) for row in rows]

    async def delete(self, entry_id: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM jarvis_ltm_entries WHERE id = $1", entry_id)

    async def clear_all(self) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM jarvis_ltm_entries")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._loop = None


def _row_to_entry(row: Any) -> MemoryEntry:
    tags_raw = row["tags"]
    meta_raw = row["metadata"]
    tags: list = json.loads(tags_raw) if isinstance(tags_raw, str) else (tags_raw or [])
    meta: dict = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})

    created_at = row["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    # asyncpg는 timezone-aware datetime 반환 — naive로 정규화
    if hasattr(created_at, "tzinfo") and created_at.tzinfo is not None:
        created_at = created_at.astimezone(UTC).replace(tzinfo=None)

    return MemoryEntry(
        id=row["id"],
        content=row["content"],
        source=row["source"],
        session_id=row["session_id"],
        tags=tags,
        metadata=meta,
        created_at=created_at,
    )
