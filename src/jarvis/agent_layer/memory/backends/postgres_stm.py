from __future__ import annotations

import asyncio
import json
from typing import Any

from jarvis.model_layer.types import AssistantMessage, Message, ToolResultMessage, UserMessage


class PostgresSTMBackend:
    """PostgreSQL 기반 단기 메모리 백엔드. asyncpg 풀 + 이벤트 루프 재생성 패턴."""

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
                CREATE TABLE IF NOT EXISTS jarvis_stm_messages (
                    id          BIGSERIAL PRIMARY KEY,
                    session_id  TEXT    NOT NULL,
                    role        TEXT    NOT NULL,
                    content_json JSONB  NOT NULL,
                    timestamp   BIGINT  NOT NULL
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_stm_session
                ON jarvis_stm_messages(session_id, id)
            """)

    async def load(self, session_id: str) -> list[Message]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT role, content_json FROM jarvis_stm_messages"
                " WHERE session_id = $1 ORDER BY id ASC",
                session_id,
            )
        result = []
        for row in rows:
            raw = row["content_json"]
            content: dict = json.loads(raw) if isinstance(raw, str) else raw
            msg = _deserialize(row["role"], content)
            if msg is not None:
                result.append(msg)
        return result

    async def append(self, session_id: str, message: Message) -> None:
        pool = await self._get_pool()
        content = json.loads(message.model_dump_json())
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO jarvis_stm_messages (session_id, role, content_json, timestamp)"
                " VALUES ($1, $2, $3::jsonb, $4)",
                session_id, message.role, json.dumps(content), message.timestamp,
            )

    async def clear(self, session_id: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM jarvis_stm_messages WHERE session_id = $1", session_id
            )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._loop = None


def _deserialize(role: str, data: dict) -> Message | None:
    try:
        if role == "user":
            return UserMessage.model_validate(data)
        elif role == "assistant":
            return AssistantMessage.model_validate(data)
        elif role == "tool_result":
            return ToolResultMessage.model_validate(data)
    except Exception:
        return None
    return None
