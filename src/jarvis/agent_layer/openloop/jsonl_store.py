from __future__ import annotations

import asyncio
import time
from pathlib import Path

import aiofiles

from jarvis.agent_layer.openloop.types import LOOP_STATUSES, OpenLoop, merge_loop, normalize_description


class JsonlOpenLoopStore:
    """JSONL append-only 기반 open-loop 영속 저장소 (로컬, git-friendly).

    각 변경(add/update_status)을 한 줄씩 append하고, 로드 시 id별 마지막 레코드로
    상태를 재구성한다(event-log replay). 상태는 메모리에 캐싱하고 변경 시 append.
    JsonlSessionRepo와 동일한 영속 철학.
    """

    def __init__(self, path: str = "~/.jarvis/openloops.jsonl") -> None:
        self._path = Path(path).expanduser()
        self._loops: dict[str, OpenLoop] = {}
        self._loaded = False
        self._lock = asyncio.Lock()

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        async with self._lock:
            if self._loaded:
                return
            if self._path.exists():
                async with aiofiles.open(self._path, encoding="utf-8") as f:
                    async for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            loop = OpenLoop.model_validate_json(line)
                        except Exception:
                            continue
                        self._loops[loop.id] = loop  # last-wins replay
            self._loaded = True

    async def _append(self, loop: OpenLoop) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(self._path, "a", encoding="utf-8") as f:
            await f.write(loop.model_dump_json() + "\n")

    async def add(self, loop: OpenLoop) -> str:
        await self._ensure_loaded()
        self._loops[loop.id] = loop
        await self._append(loop)
        return loop.id

    async def add_unique(self, loop: OpenLoop) -> str | None:
        await self._ensure_loaded()
        if not normalize_description(loop.description):
            return None
        record = merge_loop(list(self._loops.values()), loop)
        return await self.add(record) if record is not None else None

    async def list_open(self, session_id: str | None = None, limit: int = 20) -> list[OpenLoop]:
        await self._ensure_loaded()
        items = [
            x
            for x in self._loops.values()
            if x.status == "open" and (session_id is None or x.origin_session == session_id)
        ]
        items.sort(key=lambda x: x.created_at, reverse=True)
        return items[:limit]

    async def get(self, loop_id: str) -> OpenLoop | None:
        await self._ensure_loaded()
        return self._loops.get(loop_id)

    async def update_status(self, loop_id: str, status: str) -> bool:
        await self._ensure_loaded()
        loop = self._loops.get(loop_id)
        if loop is None or status not in LOOP_STATUSES:
            return False
        loop.status = status  # type: ignore[assignment]
        loop.updated_at = int(time.time() * 1000)
        await self._append(loop)  # 변경분을 새 레코드로 append (replay에서 last-wins)
        return True

    async def all(self) -> list[OpenLoop]:
        await self._ensure_loaded()
        return list(self._loops.values())
