"""[agent_layer] open-loop 을 JSONL append 로그에 영속하고 읽을 때 id별 마지막 레코드로 상태를 되살린다."""

import asyncio
import aiofiles
from pathlib import Path

from jarvis.agent_layer.openloop.openloop_store import OpenLoopStore
from jarvis.agent_layer.openloop.openloop_types import OpenLoop
from jarvis.model_layer.embeddings import Embedder

DEFAULT_PATH = "~/.jarvis/openloops.jsonl"


class JsonlOpenLoopStore(OpenLoopStore):
    """JSONL append-only 기반 open-loop 영속 저장소 (로컬, git-friendly).

    각 변경(add/update_status)을 한 줄씩 append하고, 로드 시 id별 마지막 레코드로
    상태를 재구성한다(event-log replay). 상태는 기본 클래스의 메모리에 캐싱하고 변경 시 append.
    JsonlSessionRepo와 동일한 영속 철학.
    """

    def __init__(self, path: str = DEFAULT_PATH, embedder: Embedder | None = None) -> None:
        super().__init__(embedder)
        self._path = Path(path).expanduser()
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
        await super().add(loop)
        await self._append(loop)
        return loop.id

    async def add_unique(self, loop: OpenLoop) -> str | None:
        await self._ensure_loaded()
        return await super().add_unique(loop)

    async def list_open(self, session_id: str | None = None, limit: int = 20) -> list[OpenLoop]:
        await self._ensure_loaded()
        return await super().list_open(session_id=session_id, limit=limit)

    async def get(self, loop_id: str) -> OpenLoop | None:
        await self._ensure_loaded()
        return await super().get(loop_id)

    async def update_status(self, loop_id: str, status: str) -> bool:
        await self._ensure_loaded()
        if not await super().update_status(loop_id, status):
            return False
        await self._append(self._loops[loop_id])  # 변경분을 새 레코드로 append (replay에서 last-wins)
        return True

    async def all(self) -> list[OpenLoop]:
        await self._ensure_loaded()
        return await super().all()
