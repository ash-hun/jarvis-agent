"""[agent_layer] open-loop 저장소 기본 클래스(메모리 저장 동작)와 기한 지난 항목 닫기를 둔다."""

from __future__ import annotations

import time

from jarvis.agent_layer.openloop.types import (
    LOOP_STATUSES,
    OpenLoop,
    expired_ids,
    merge_loop,
    normalize_description,
)

# 만료 검사 때 보는 열린 항목 상한. 세션마다 몇 건이라 넉넉하다
EXPIRE_SCAN_LIMIT = 200


class OpenLoopStore:
    """open-loop 저장소 기본 클래스. 그대로 쓰면 프로세스 메모리에 담는 저장소로 동작한다.

    LTM과 달리 상태 변경(open→done/dismissed)이 잦아 전용 update API를 제공한다.
    영속 저장소(jsonl / postgres)는 상속해서 저장 매체에 맞게 재정의한다.
    """

    def __init__(self) -> None:
        self._loops: dict[str, OpenLoop] = {}

    async def add(self, loop: OpenLoop) -> str:
        self._loops[loop.id] = loop
        return loop.id

    async def add_unique(self, loop: OpenLoop) -> str | None:
        """같은 세션의 열린 같은 약속이 있으면 기한만 갱신하고, 바뀔 게 없으면 None 반환."""
        if not normalize_description(loop.description):
            return None
        record = merge_loop(list(self._loops.values()), loop)
        return await self.add(record) if record is not None else None

    async def list_open(self, session_id: str | None = None, limit: int = 20) -> list[OpenLoop]:
        items = [
            x
            for x in self._loops.values()
            if x.status == "open" and (session_id is None or x.origin_session == session_id)
        ]
        items.sort(key=lambda x: x.created_at, reverse=True)
        return items[:limit]

    async def get(self, loop_id: str) -> OpenLoop | None:
        return self._loops.get(loop_id)

    async def update_status(self, loop_id: str, status: str) -> bool:
        loop = self._loops.get(loop_id)
        if loop is None or status not in LOOP_STATUSES:
            return False
        loop.status = status  # type: ignore[assignment]
        loop.updated_at = int(time.time() * 1000)
        return True

    async def all(self) -> list[OpenLoop]:
        return list(self._loops.values())


class InMemoryOpenLoopStore(OpenLoopStore):
    """테스트·로컬용 in-memory 구현. 프로세스 재시작 시 소멸(영속화는 후속). 동작은 기본 클래스 그대로다."""


async def close_expired(
    store: OpenLoopStore, now_ms: int, grace_ms: int, max_age_ms: int, session_id: str | None = None
) -> list[str]:
    """기한이 지난 열린 항목을 expired 로 닫는다. 이미 닫힌 건 다시 보지 않으므로 두 번 불러도 같다."""
    loops = await store.list_open(session_id=session_id, limit=EXPIRE_SCAN_LIMIT)
    ids = expired_ids(loops, now_ms, grace_ms, max_age_ms)
    for loop_id in ids:
        await store.update_status(loop_id, "expired")
    return ids
