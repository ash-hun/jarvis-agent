from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import aiosqlite

from jarvis.model_layer.types import AssistantMessage, Message, ToolResultMessage, UserMessage


class SqliteMemory:
    """SQLite 기반 영속 메모리. 모든 메시지를 저장하고 최근 N개를 transform으로 주입."""

    def __init__(self, db_path: str = "~/.jarvis/memory.db", window_size: int = 50) -> None:
        self._db_path = str(Path(db_path).expanduser())
        self._window_size = window_size
        self._initialized = False

    async def _ensure_init(self) -> None:
        if self._initialized:
            return
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    timestamp INTEGER NOT NULL
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_session ON messages(session_id, id)")
            await db.commit()
        self._initialized = True

    async def transform(
        self,
        messages: list[Message],
        context: dict[str, Any],
    ) -> list[Message]:
        # transform에서는 현재 in-flight 메시지 리스트를 그대로 반환
        # (필요 시 DB에서 추가 컨텍스트를 주입하는 식으로 확장 가능)
        return messages

    async def store(self, message: Message, context: dict[str, Any]) -> None:
        await self._ensure_init()
        sid = context.get("session_id", "default")
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO messages (session_id, role, content_json, timestamp) VALUES (?, ?, ?, ?)",
                (sid, message.role, message.model_dump_json(), message.timestamp),
            )
            await db.commit()

    async def retrieve(
        self,
        query: str,
        context: dict[str, Any],
        limit: int = 10,
    ) -> list[Message]:
        await self._ensure_init()
        sid = context.get("session_id", "default")
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT role, content_json FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (sid, limit),
            )
            rows = await cursor.fetchall()

        return [_deserialize(role, content) for role, content in reversed(rows) if _deserialize(role, content)]

    async def clear(self, context: dict[str, Any]) -> None:
        await self._ensure_init()
        sid = context.get("session_id", "default")
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
            await db.commit()


def _deserialize(role: str, content_json: str) -> Message | None:
    try:
        data = json.loads(content_json)
        if role == "user":
            return UserMessage.model_validate(data)
        elif role == "assistant":
            return AssistantMessage.model_validate(data)
        elif role == "tool_result":
            return ToolResultMessage.model_validate(data)
    except Exception:
        return None
    return None
