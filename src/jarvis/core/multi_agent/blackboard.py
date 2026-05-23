"""SharedBlackboard — Blackboard 아키텍처의 공유 상태 저장소.

에이전트들은 write()로 결과를 게시하고 read()로 타 에이전트 결과를 참조한다.
watch() / watch_all()은 asyncio.Queue 기반 알림 — 폴링 없이 변경을 구독한다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class BlackboardEntry:
    key: str
    value: Any
    author: str
    written_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SharedBlackboard:
    def __init__(self) -> None:
        self._data: dict[str, BlackboardEntry] = {}
        self._key_watchers: dict[str, list[asyncio.Queue[BlackboardEntry]]] = {}
        self._global_watchers: list[asyncio.Queue[BlackboardEntry]] = []

    # ── 읽기/쓰기 ─────────────────────────────────────────────────────────────

    async def write(self, key: str, value: Any, author: str) -> None:
        entry = BlackboardEntry(key=key, value=value, author=author)
        self._data[key] = entry
        for q in self._key_watchers.get(key, []):
            await q.put(entry)
        for q in self._global_watchers:
            await q.put(entry)

    def read(self, key: str) -> Any | None:
        entry = self._data.get(key)
        return entry.value if entry else None

    def read_entry(self, key: str) -> BlackboardEntry | None:
        return self._data.get(key)

    def snapshot(self) -> dict[str, Any]:
        """현재 전체 상태의 불변 스냅샷 반환."""
        return {k: v.value for k, v in self._data.items()}

    # ── 구독 ──────────────────────────────────────────────────────────────────

    async def watch(self, key: str) -> asyncio.Queue[BlackboardEntry]:
        """특정 키 변경 구독. 반환된 Queue에서 get()으로 변경 수신."""
        q: asyncio.Queue[BlackboardEntry] = asyncio.Queue()
        self._key_watchers.setdefault(key, []).append(q)
        return q

    async def watch_all(self) -> asyncio.Queue[BlackboardEntry]:
        """모든 키 변경 구독."""
        q: asyncio.Queue[BlackboardEntry] = asyncio.Queue()
        self._global_watchers.append(q)
        return q

    # ── 삭제 ──────────────────────────────────────────────────────────────────

    def clear(self, key: str | None = None) -> None:
        if key is not None:
            self._data.pop(key, None)
        else:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: str) -> bool:
        return key in self._data
