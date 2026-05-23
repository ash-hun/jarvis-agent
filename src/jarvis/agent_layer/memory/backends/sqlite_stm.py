from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from jarvis.model_layer.types import AssistantMessage, Message, ToolResultMessage, UserMessage


class SqliteSTMBackend:
    """SQLite 기반 단기 메모리 백엔드. 세션별 메시지 이력을 append-only로 저장."""

    def __init__(self, db_path: str = "~/.jarvis/stm.db") -> None:
        self._db_path = str(Path(db_path).expanduser())
        self._initialized = False

    async def _ensure_init(self) -> None:
        if self._initialized:
            return
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS stm_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    timestamp INTEGER NOT NULL
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_stm_session ON stm_messages(session_id, id)"
            )
            await db.commit()
        self._initialized = True

    async def load(self, session_id: str) -> list[Message]:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT role, content_json FROM stm_messages"
                " WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            )
            rows = await cursor.fetchall()
        result = []
        for role, content_json in rows:
            msg = _deserialize(role, content_json)
            if msg is not None:
                result.append(msg)
        return result

    async def append(self, session_id: str, message: Message) -> None:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO stm_messages (session_id, role, content_json, timestamp)"
                " VALUES (?, ?, ?, ?)",
                (session_id, message.role, message.model_dump_json(), message.timestamp),
            )
            await db.commit()

    async def clear(self, session_id: str) -> None:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "DELETE FROM stm_messages WHERE session_id = ?", (session_id,)
            )
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
