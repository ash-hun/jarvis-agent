"""[memory] 기존 jarvis_ltm_entries 테이블에 범위 컬럼을 멱등하게 덧붙여 쓰는 PostgreSQL 장기 기억 저장소."""

import json
import asyncio
import contextlib
from typing import Any
from datetime import UTC, datetime
from collections.abc import Sequence

from jarvis.memory.scope import MAIN_AGENT, PRIVATE, SHARED, MemoryScope
from jarvis.memory.types import REFERENT, MemoryItem, MemoryKind
from jarvis.memory.stores.protocol import ItemStore, tokens_of
from jarvis.common.logger import get_logger

logger = get_logger(__name__)

TABLE = "jarvis_ltm_entries"

# 범위 도입 전 행의 source 를 kind 로 역산하는 규칙. 바뀌면 backfill 결과가 달라지므로 고정값이다.
_LEGACY_KIND_SQL = """
    CASE source
        WHEN 'explicit' THEN 'semantic'
        WHEN 'usermodel' THEN 'semantic'
        ELSE 'episodic'
    END
"""

_BASE_COLUMNS = (
    "id, content, source, session_id, tags, metadata, created_at, "
    "kind, visibility, author, user_id, agent_id, importance, occurred_at, valid_from, "
    "superseded_by, rehearsal_count, last_accessed"
)
# pgvector 의 vector 타입은 asyncpg 코덱 없이 문자열로 주고받는다: '[0.1,0.2]'
_COLUMNS = _BASE_COLUMNS + ", embedding::text AS embedding, embedding_model"
_COLUMNS_NO_VECTOR = _BASE_COLUMNS + ", NULL::text AS embedding, NULL::text AS embedding_model"

# 읽기 상속 규칙. 전역(user_id NULL) 항목은 모두에게, 그 외는 같은 사용자의 내 에이전트 항목 또는 shared.
_VISIBLE = (
    "(user_id IS NULL OR user_id = $1) AND (agent_id = $2 OR visibility = $3) AND superseded_by IS NULL"
)


# 키워드 매칭 대상. 상대 지칭으로 쓴 항목은 가리킨 대화(metadata.referent)로도 찾힌다
_SEARCH_TEXT = f"(content || ' ' || COALESCE(metadata->>'{REFERENT}', ''))"


class PostgresItemStore(ItemStore):
    def __init__(self, dsn: str, dimensions: int = 0) -> None:
        """dimensions > 0 이면 pgvector 컬럼을 만들고 의미 검색을 켠다. 확장이 없으면 키워드 검색으로 내려간다."""
        super().__init__()
        self._dsn = dsn
        self._dimensions = dimensions
        self._vector = False  # 마이그레이션 뒤 실제로 vector 컬럼을 쓸 수 있는지
        self._pool: Any = None  # asyncpg 는 스텁이 없어 Pool 타입을 쓸 수 없다
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def vector_enabled(self) -> bool:
        return self._vector

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
            # backfill: 범위 도입 전 행은 전역(user_id NULL), 메인 에이전트로 둔다. 사용자에 대한 사실만 shared 이고
            # 일화는 main 전용이다. 메인 관점에서는 전부 그대로 보인다. kind 가 채워진 행은 건드리지 않는다.
            await conn.execute(f"""
                UPDATE {TABLE} SET
                    kind            = {_LEGACY_KIND_SQL},
                    visibility      = COALESCE(visibility, CASE WHEN {_LEGACY_KIND_SQL} = 'semantic'
                                                                THEN '{SHARED}' ELSE '{PRIVATE}' END),
                    agent_id        = COALESCE(agent_id, '{MAIN_AGENT}'),
                    author          = COALESCE(author, CASE WHEN source = 'explicit' THEN 'user' ELSE 'agent' END),
                    importance      = COALESCE(importance, 0.5),
                    rehearsal_count = COALESCE(rehearsal_count, 0)
                WHERE kind IS NULL
            """)
            # 예전 backfill 은 일화까지 shared 로 두어 다른 최상위 에이전트에 대화가 보였다. 지금 쓰기 경로는
            # 일화를 shared 로 쓰지 않으므로(WRITE_RULES) shared 일화는 그 backfill 행뿐이다. 두 번 돌려도 같다
            await conn.execute(
                f"UPDATE {TABLE} SET visibility = '{PRIVATE}' WHERE kind = 'episodic' AND visibility = '{SHARED}'"
            )
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_ltm_scope ON {TABLE}(user_id, agent_id, kind)"
            )
            await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_ltm_created ON {TABLE}(created_at DESC)")
            await conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS embedding_model TEXT")
            self._vector = await self._ensure_vector(conn)

    async def _ensure_vector(self, conn: Any) -> bool:
        """pgvector 확장과 vector 컬럼. 확장을 못 만들면(이미지에 없음) 조용히 키워드 검색만 쓴다."""
        if self._dimensions <= 0:
            return False
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS embedding vector({self._dimensions})")
        except Exception as exc:
            logger.info(f"[Memory] pgvector unavailable, keyword search only: {exc}")
            return False
        # hnsw 는 pgvector 0.5 이상. 없으면 순차 스캔으로도 동작한다
        with contextlib.suppress(Exception):
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_ltm_embedding ON {TABLE} USING hnsw (embedding vector_cosine_ops)"
            )
        return True

    async def store(self, item: MemoryItem) -> str:
        pool = await self._get_pool()
        vector_cols = ", embedding, embedding_model" if self._vector else ", embedding_model"
        vector_vals = ", $19::vector, $20" if self._vector else ", $19"
        vector_set = (
            ", embedding = EXCLUDED.embedding, embedding_model = EXCLUDED.embedding_model"
            if self._vector else ", embedding_model = EXCLUDED.embedding_model"
        )
        params: list[Any] = [
            item.id, item.content, item.source, item.scope.session_id,
            json.dumps(item.tags, ensure_ascii=False), json.dumps(item.metadata, ensure_ascii=False),
            item.created_at,
            str(item.kind), item.visibility, item.author, item.scope.user_id, item.scope.agent_id,
            item.importance, item.occurred_at, item.valid_from, item.superseded_by,
            item.rehearsal_count, item.last_accessed,
        ]
        if self._vector:
            params.append(_vec(item.embedding))
        params.append(item.embedding_model)
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {TABLE} ({_BASE_COLUMNS}{vector_cols})
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7,
                        $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18{vector_vals})
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content, source = EXCLUDED.source, session_id = EXCLUDED.session_id,
                    tags = EXCLUDED.tags, metadata = EXCLUDED.metadata, created_at = EXCLUDED.created_at,
                    kind = EXCLUDED.kind, visibility = EXCLUDED.visibility, author = EXCLUDED.author,
                    user_id = EXCLUDED.user_id, agent_id = EXCLUDED.agent_id, importance = EXCLUDED.importance,
                    occurred_at = EXCLUDED.occurred_at, valid_from = EXCLUDED.valid_from,
                    superseded_by = EXCLUDED.superseded_by, rehearsal_count = EXCLUDED.rehearsal_count,
                    last_accessed = EXCLUDED.last_accessed{vector_set}
                """,
                *params,
            )
        return item.id

    def _cols(self) -> str:
        return _COLUMNS if self._vector else _COLUMNS_NO_VECTOR

    async def get(self, item_id: str) -> MemoryItem | None:
        pool = await self._get_pool()
        cols = self._cols()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT {cols} FROM {TABLE} WHERE id = $1", item_id)
        return _row_to_item(row) if row else None

    async def search(
        self,
        query: str,
        scope: MemoryScope,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 10,
        query_embedding: list[float] | None = None,
        min_similarity: float = 0.3,
    ) -> list[MemoryItem]:
        pool = await self._get_pool()  # 마이그레이션이 끝나야 _vector 가 정해진다
        tokens = tokens_of(query)
        use_vector = self._vector and query_embedding is not None
        if not tokens and not use_vector:
            return []
        params: list[Any] = [scope.user_id, scope.agent_id, SHARED]
        where = [_VISIBLE]
        if kinds:
            params.append([str(k) for k in kinds])
            where.append(f"kind = ANY(${len(params)})")
        matches = []
        for t in tokens:
            params.append(f"%{t}%")
            matches.append(f"{_SEARCH_TEXT} ILIKE ${len(params)}")
        vector_where = ""
        if use_vector:
            params.append(_vec(query_embedding))
            vec = f"${len(params)}::vector"
            params.append(min_similarity)
            vector_where = f"embedding IS NOT NULL AND 1 - (embedding <=> {vec}) >= ${len(params)}"
            matches.append(f"({vector_where})")
        params.append(limit)
        lim = f"${len(params)}"
        hit = " AND ".join([*where, "(" + " OR ".join(matches) + ")"])
        # 최신순 하나로만 자르면 오래됐지만 중요하거나 가장 가까운 항목이 점수를 받기도 전에 빠진다
        parts = [
            f"(SELECT {self._cols()} FROM {TABLE} WHERE {hit} ORDER BY created_at DESC LIMIT {lim})",
            f"(SELECT {self._cols()} FROM {TABLE} WHERE {hit} ORDER BY importance DESC, created_at DESC LIMIT {lim})",
        ]
        if use_vector:
            near = " AND ".join([*where, vector_where])
            parts.append(f"(SELECT {self._cols()} FROM {TABLE} WHERE {near} ORDER BY embedding <=> {vec} LIMIT {lim})")
        async with pool.acquire() as conn:
            rows = await conn.fetch(" UNION ALL ".join(parts), *params)
        items = {r["id"]: r for r in rows}
        return [_row_to_item(r) for r in items.values()]

    async def recent(
        self,
        scope: MemoryScope,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        return await self._select(scope, kinds, "created_at DESC", limit)

    async def important(
        self,
        scope: MemoryScope,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        return await self._select(scope, kinds, "importance DESC, created_at DESC", limit)

    async def _select(
        self, scope: MemoryScope, kinds: Sequence[MemoryKind] | None, order: str, limit: int
    ) -> list[MemoryItem]:
        pool = await self._get_pool()
        params: list[Any] = [scope.user_id, scope.agent_id, SHARED]
        where = [_VISIBLE]
        if kinds:
            params.append([str(k) for k in kinds])
            where.append(f"kind = ANY(${len(params)})")
        params.append(limit)
        sql = (
            f"SELECT {self._cols()} FROM {TABLE} WHERE {' AND '.join(where)}"
            f" ORDER BY {order} LIMIT ${len(params)}"
        )
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_row_to_item(r) for r in rows]

    async def touch(self, item_ids: Sequence[str], at: datetime) -> None:
        if not item_ids:
            return
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"UPDATE {TABLE} SET last_accessed = $2 WHERE id = ANY($1)", list(item_ids), at)

    async def supersede(self, old_id: str, new_id: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"UPDATE {TABLE} SET superseded_by = $2 WHERE id = $1", old_id, new_id)

    async def delete(self, item_id: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DELETE FROM {TABLE} WHERE id = $1", item_id)

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


def _vec(embedding: list[float] | None) -> str | None:
    return None if embedding is None else "[" + ",".join(repr(float(x)) for x in embedding) + "]"


def _parse_vec(text: str | None) -> list[float] | None:
    if not text:
        return None
    return [float(x) for x in text.strip("[]").split(",") if x]


def _naive(value: Any) -> datetime | None:
    if value is None:
        return None
    parsed: datetime = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is not None:  # asyncpg 는 aware 로 돌려준다. 코드 전체가 naive 를 쓴다
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


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
        embedding=_parse_vec(row["embedding"]),
        embedding_model=row["embedding_model"],
    )


def like_prefix(prefix: str) -> str:
    """LIKE 접두어 패턴. 세션 id 의 '_' 와 '%' 는 글자 그대로 본다."""
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
