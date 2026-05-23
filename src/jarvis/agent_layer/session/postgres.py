from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from jarvis.agent_layer.session.protocol import SessionMetadata, deserialize_message
from jarvis.model_layer.types import Message


class PostgresSessionRepo:
    """
    PostgreSQL 기반 세션 영속성.
    asyncpg 커넥션 풀을 사용하며 이벤트 루프가 바뀌면 풀을 자동 재생성한다.

    테이블 스키마는 _ensure_tables()에서 자동 생성(CREATE IF NOT EXISTS).

    환경변수: JARVIS_SESSION__POSTGRES_DSN=postgresql://user:pw@host:5432/db
    """

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
                CREATE TABLE IF NOT EXISTS jarvis_sessions (
                    session_id    TEXT    PRIMARY KEY,
                    cwd           TEXT    NOT NULL,
                    parent_id     TEXT,
                    created_at    BIGINT  NOT NULL,
                    updated_at    BIGINT  NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0
                )
            """)
            # 기존 테이블에 parent_id 컬럼이 없으면 추가 (하위 호환)
            await conn.execute("""
                ALTER TABLE jarvis_sessions ADD COLUMN IF NOT EXISTS parent_id TEXT
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS jarvis_entries (
                    id          TEXT    PRIMARY KEY,
                    session_id  TEXT    NOT NULL REFERENCES jarvis_sessions(session_id) ON DELETE CASCADE,
                    parent_id   TEXT,
                    timestamp   BIGINT  NOT NULL,
                    type        TEXT    NOT NULL,
                    content     JSONB   NOT NULL
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_jarvis_entries_session_id
                ON jarvis_entries(session_id, timestamp)
            """)

    async def create(self, session_id: str | None = None, cwd: str = ".") -> SessionMetadata:
        pool = await self._get_pool()
        sid = session_id or str(uuid.uuid4())
        now = int(time.time() * 1000)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO jarvis_sessions (session_id, cwd, parent_id, created_at, updated_at, message_count)
                VALUES ($1, $2, NULL, $3, $4, 0)
                ON CONFLICT (session_id) DO NOTHING
                """,
                sid, cwd, now, now,
            )
        return SessionMetadata(
            session_id=sid, cwd=cwd, created_at=now, updated_at=now, message_count=0
        )

    async def list(self, cwd: str = "") -> list[SessionMetadata]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if cwd:
                rows = await conn.fetch(
                    "SELECT * FROM jarvis_sessions WHERE cwd = $1 ORDER BY updated_at DESC", cwd
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM jarvis_sessions ORDER BY updated_at DESC"
                )
        return [SessionMetadata(**dict(row)) for row in rows]

    async def create_branch(self, parent_session_id: str) -> SessionMetadata:
        pool = await self._get_pool()
        branch_id = str(uuid.uuid4())
        now = int(time.time() * 1000)
        async with pool.acquire() as conn:
            parent_row = await conn.fetchrow(
                "SELECT * FROM jarvis_sessions WHERE session_id = $1", parent_session_id
            )
            if not parent_row:
                raise ValueError(f"Parent session {parent_session_id!r} not found")
            parent_cwd: str = parent_row["cwd"]
            parent_count: int = parent_row["message_count"]

            await conn.execute(
                """
                INSERT INTO jarvis_sessions
                    (session_id, cwd, parent_id, created_at, updated_at, message_count)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                branch_id, parent_cwd, parent_session_id, now, now, parent_count,
            )
            # 부모 메시지를 브랜치에 복사
            await conn.execute(
                """
                INSERT INTO jarvis_entries (id, session_id, parent_id, timestamp, type, content)
                SELECT gen_random_uuid()::text, $1, parent_id, timestamp, type, content
                FROM jarvis_entries
                WHERE session_id = $2 AND type = 'message'
                ORDER BY timestamp
                """,
                branch_id, parent_session_id,
            )
        return SessionMetadata(
            session_id=branch_id,
            cwd=parent_cwd,
            created_at=now,
            updated_at=now,
            message_count=parent_count,
            parent_id=parent_session_id,
        )

    async def get_messages(self, session_id: str) -> list[Message]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT content FROM jarvis_entries
                WHERE session_id = $1 AND type = 'message'
                ORDER BY timestamp
                """,
                session_id,
            )
        messages: list[Message] = []
        for row in rows:
            raw = row["content"]
            # asyncpg는 JSONB를 버전/설정에 따라 str 또는 dict로 반환
            content: dict[str, Any] = json.loads(raw) if isinstance(raw, str) else raw
            msg = deserialize_message(content)
            if msg:
                messages.append(msg)
        return messages

    async def append(self, session_id: str, message: Message) -> str:
        pool = await self._get_pool()
        entry_id = str(uuid.uuid4())
        now = int(time.time() * 1000)
        content = json.loads(message.model_dump_json())
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO jarvis_entries (id, session_id, parent_id, timestamp, type, content)
                VALUES ($1, $2, $3, $4, 'message', $5::jsonb)
                """,
                entry_id, session_id, None, now, json.dumps(content),
            )
            await conn.execute(
                """
                UPDATE jarvis_sessions
                SET updated_at = $1, message_count = message_count + 1
                WHERE session_id = $2
                """,
                now, session_id,
            )
        return entry_id

    async def delete(self, session_id: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM jarvis_sessions WHERE session_id = $1", session_id
            )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._loop = None
