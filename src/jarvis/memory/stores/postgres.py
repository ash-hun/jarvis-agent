"""PostgreSQL 저장소. 기존 jarvis_ltm_entries 테이블을 그대로 쓰고 범위 컬럼을 멱등하게 덧붙인다."""

import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from jarvis.memory.scope import MAIN_AGENT, SHARED, MemoryScope
from jarvis.memory.stores.protocol import tokens_of
from jarvis.memory.types import MemoryItem, MemoryKind

TABLE = "jarvis_ltm_entries"

# 범위 도입 전 행의 source 를 kind 로 역산하는 규칙. 바뀌면 backfill 결과가 달라지므로 고정값이다.
_LEGACY_KIND_SQL = """
    CASE source
        WHEN 'explicit' THEN 'semantic'
        WHEN 'usermodel' THEN 'semantic'
        ELSE 'episodic'
    END
"""

_COLUMNS = (
    "id, content, source, session_id, tags, metadata, created_at, "
    "kind, visibility, author, user_id, agent_id, importance, occurred_at, valid_from, "
    "superseded_by, rehearsal_count, last_accessed"
)

# 읽기 상속 규칙. 전역(user_id NULL) 항목은 모두에게, 그 외는 같은 사용자의 내 에이전트 항목 또는 shared.
_VISIBLE = (
    "(user_id IS NULL OR user_id = $1) AND (agent_id = $2 OR visibility = $3) AND superseded_by IS NULL"
)


class PostgresItemStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Any = None
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
            await self._migrate()
        return self._pool

    async def _migrate(self) -> None:
        """두 번 돌려도 같은 스키마와 같은 행으로 수렴한다."""
        async with self._pool.acquire() as conn:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    id          TEXT        PRIMARY KEY,
                    content     TEXT        NOT NULL,
                    source      TEXT        NOT NULL DEFAULT 'explicit',
                    session_id  TEXT,
                    tags        JSONB       NOT NULL DEFAULT '[]',
                    metadata    JSONB       NOT NULL DEFAULT '{{}}',
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            for ddl in (
                "kind TEXT",
                "visibility TEXT",
                "author TEXT",
                "user_id TEXT",
                "agent_id TEXT",
                "importance DOUBLE PRECISION",
                "occurred_at TIMESTAMPTZ",
                "valid_from TIMESTAMPTZ",
                "superseded_by TEXT",
                "rehearsal_count INTEGER",
                "last_accessed TIMESTAMPTZ",
            ):
                await conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS {ddl}")
            # backfill: 범위 도입 전 행은 전역(user_id NULL), 메인 에이전트, shared 로 둔다.
            # 메인 에이전트 관점에서 보이던 것이 그대로 보인다. kind 가 채워진 행은 건드리지 않는다.
            await conn.execute(f"""
                UPDATE {TABLE} SET
                    kind            = {_LEGACY_KIND_SQL},
                    visibility      = COALESCE(visibility, '{SHARED}'),
                    agent_id        = COALESCE(agent_id, '{MAIN_AGENT}'),
                    author          = COALESCE(author, CASE WHEN source = 'explicit' THEN 'user' ELSE 'agent' END),
                    importance      = COALESCE(importance, 0.5),
                    rehearsal_count = COALESCE(rehearsal_count, 0)
                WHERE kind IS NULL
            """)
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_ltm_scope ON {TABLE}(user_id, agent_id, kind)"
            )
            await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_ltm_created ON {TABLE}(created_at DESC)")

    async def store(self, item: MemoryItem) -> str:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {TABLE} ({_COLUMNS})
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7,
                        $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content, source = EXCLUDED.source, session_id = EXCLUDED.session_id,
                    tags = EXCLUDED.tags, metadata = EXCLUDED.metadata, created_at = EXCLUDED.created_at,
                    kind = EXCLUDED.kind, visibility = EXCLUDED.visibility, author = EXCLUDED.author,
                    user_id = EXCLUDED.user_id, agent_id = EXCLUDED.agent_id, importance = EXCLUDED.importance,
                    occurred_at = EXCLUDED.occurred_at, valid_from = EXCLUDED.valid_from,
                    superseded_by = EXCLUDED.superseded_by, rehearsal_count = EXCLUDED.rehearsal_count,
                    last_accessed = EXCLUDED.last_accessed
                """,
                item.id, item.content, item.source, item.scope.session_id,
                json.dumps(item.tags, ensure_ascii=False), json.dumps(item.metadata, ensure_ascii=False),
                item.created_at,
                str(item.kind), item.visibility, item.author, item.scope.user_id, item.scope.agent_id,
                item.importance, item.occurred_at, item.valid_from, item.superseded_by,
                item.rehearsal_count, item.last_accessed,
            )
        return item.id

    async def get(self, item_id: str) -> MemoryItem | None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT {_COLUMNS} FROM {TABLE} WHERE id = $1", item_id)
        return _row_to_item(row) if row else None

    async def search(
        self,
        query: str,
        scope: MemoryScope,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        tokens = tokens_of(query)
        if not tokens:
            return []
        params: list[Any] = [scope.user_id, scope.agent_id, SHARED]
        where = [_VISIBLE]
        if kinds:
            params.append([str(k) for k in kinds])
            where.append(f"kind = ANY(${len(params)})")
        like = []
        for t in tokens:
            params.append(f"%{t}%")
            like.append(f"content ILIKE ${len(params)}")
        where.append("(" + " OR ".join(like) + ")")
        params.append(limit)
        sql = (
            f"SELECT {_COLUMNS} FROM {TABLE} WHERE {' AND '.join(where)}"
            f" ORDER BY created_at DESC LIMIT ${len(params)}"
        )
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_row_to_item(r) for r in rows]

    async def recent(
        self,
        scope: MemoryScope,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        params: list[Any] = [scope.user_id, scope.agent_id, SHARED]
        where = [_VISIBLE]
        if kinds:
            params.append([str(k) for k in kinds])
            where.append(f"kind = ANY(${len(params)})")
        params.append(limit)
        sql = (
            f"SELECT {_COLUMNS} FROM {TABLE} WHERE {' AND '.join(where)}"
            f" ORDER BY created_at DESC LIMIT ${len(params)}"
        )
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_row_to_item(r) for r in rows]

    async def supersede(self, old_id: str, new_id: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"UPDATE {TABLE} SET superseded_by = $2 WHERE id = $1", old_id, new_id)

    async def delete(self, item_id: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DELETE FROM {TABLE} WHERE id = $1", item_id)

    async def clear(self, scope: MemoryScope | None = None) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if scope is None:
                await conn.execute(f"DELETE FROM {TABLE}")
            else:
                await conn.execute(
                    f"DELETE FROM {TABLE} WHERE user_id IS NOT DISTINCT FROM $1 AND agent_id = $2",
                    scope.user_id, scope.agent_id,
                )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._loop = None


def _naive(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is not None:  # asyncpg 는 aware 로 돌려준다. 코드 전체가 naive 를 쓴다
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value


def _row_to_item(row: Any) -> MemoryItem:
    tags_raw, meta_raw = row["tags"], row["metadata"]
    return MemoryItem(
        id=row["id"],
        content=row["content"],
        source=row["source"],
        kind=MemoryKind(row["kind"]),
        scope=MemoryScope(user_id=row["user_id"], agent_id=row["agent_id"], session_id=row["session_id"]),
        visibility=row["visibility"],
        author=row["author"],
        importance=row["importance"],
        tags=json.loads(tags_raw) if isinstance(tags_raw, str) else (tags_raw or []),
        metadata=json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {}),
        occurred_at=_naive(row["occurred_at"]),
        valid_from=_naive(row["valid_from"]),
        superseded_by=row["superseded_by"],
        rehearsal_count=row["rehearsal_count"],
        last_accessed=_naive(row["last_accessed"]),
        created_at=_naive(row["created_at"]) or datetime.now(),
    )
