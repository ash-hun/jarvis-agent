"""[core] 에이전트가 결과를 게시하고 읽으며 asyncio.Queue 로 변경을 구독하는 공유 블랙보드 저장소."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class BlackboardEntry:
    key: str
    value: Any  # 블랙보드는 작업 문구, 결과 문자열, 임의 구조를 함께 담는다
    author: str
    written_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class SharedBlackboard:
    """write() 로 게시, read() 로 참조. watch() / watch_all() 은 폴링 없이 변경을 구독하는 Queue 를 준다."""

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
