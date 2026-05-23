from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import aiosqlite

from jarvis.agent_layer.memory.backends.protocol import MemoryEntry


class SqliteLTMBackend:
    """
    SQLite 기반 장기 메모리 백엔드 (세션 횡단).
    키워드 LIKE 검색. 의미론적 검색이 필요하면 pgvector/Chroma 구현체로 교체.
    """

    def __init__(self, db_path: str = "~/.jarvis/ltm.db") -> None:
        self._db_path = str(Path(db_path).expanduser())
        self._initialized = False

    async def _ensure_init(self) -> None:
        if self._initialized:
            return
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ltm_entries (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'explicit',
                    session_id TEXT,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_ltm_created ON ltm_entries(created_at DESC)"
            )
            await db.commit()
        self._initialized = True

    async def store(self, entry: MemoryEntry) -> str:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO ltm_entries"
                " (id, content, source, session_id, tags_json, metadata_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.id,
                    entry.content,
                    entry.source,
                    entry.session_id,
                    json.dumps(entry.tags, ensure_ascii=False),
                    json.dumps(entry.metadata, ensure_ascii=False),
                    entry.created_at.isoformat(),
                ),
            )
            await db.commit()
        return entry.id

    async def search(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        """토큰 단위 OR 검색 — 쿼리를 공백으로 분리하고 각 토큰을 LIKE 절로 연결."""
        await self._ensure_init()
        tokens = [t for t in query.split() if t]
        if not tokens:
            return []

        clauses = " OR ".join("content LIKE ?" for _ in tokens)
        params: list = [f"%{t}%" for t in tokens] + [limit]
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                f"SELECT id, content, source, session_id, tags_json, metadata_json, created_at"
                f" FROM ltm_entries WHERE {clauses}"
                f" ORDER BY created_at DESC LIMIT ?",
                params,
            )
            rows = await cursor.fetchall()
        return [_row_to_entry(row) for row in rows]

    async def get_recent(self, limit: int = 10) -> list[MemoryEntry]:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT id, content, source, session_id, tags_json, metadata_json, created_at"
                " FROM ltm_entries ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
        return [_row_to_entry(row) for row in rows]

    async def delete(self, entry_id: str) -> None:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM ltm_entries WHERE id = ?", (entry_id,))
            await db.commit()

    async def clear_all(self) -> None:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM ltm_entries")
            await db.commit()


def _row_to_entry(row: tuple) -> MemoryEntry:
    entry_id, content, source, session_id, tags_json, metadata_json, created_at_str = row
    return MemoryEntry(
        id=entry_id,
        content=content,
        source=source,
        session_id=session_id,
        tags=json.loads(tags_json),
        metadata=json.loads(metadata_json),
        created_at=datetime.fromisoformat(created_at_str),
    )
