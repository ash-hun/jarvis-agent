"""[agent_layer] open-loop 저장소 기본 클래스(메모리 저장 동작)와 기한 지난 항목 닫기를 둔다."""

import time

from jarvis.agent_layer.openloop.types import (
    LOOP_STATUSES,
    OpenLoop,
    expired_ids,
    merge_loop,
    normalize_description,
)
from jarvis.model_layer.embeddings import Embedder, cosine

# 만료 검사 때 보는 열린 항목 상한. 세션마다 몇 건이라 넉넉하다
EXPIRE_SCAN_LIMIT = 200
# 기억해 둘 약속 벡터 수. 세션 여럿의 열린 약속이 들어가고, 넘치면 가장 오래 안 쓴 것부터 버린다
VECTOR_CACHE_MAX = 256


class OpenLoopStore:
    """open-loop 저장소 기본 클래스. 그대로 쓰면 프로세스 메모리에 담는 저장소로 동작한다.

    LTM과 달리 상태 변경(open→done/dismissed)이 잦아 전용 update API를 제공한다.
    영속 저장소(jsonl / postgres)는 상속해서 저장 매체에 맞게 재정의한다.
    embedder 가 있으면 같은 약속 판정에 임베딩 유사도를 더한다.
    """

    def __init__(self, embedder: Embedder | None = None) -> None:
        self._loops: dict[str, OpenLoop] = {}
        self._embedder = embedder
        # 설명 → 벡터. 같은 모델이면 같은 글의 벡터는 같아서 열린 약속을 매번 다시 임베딩하지 않는다
        self._vectors: dict[str, list[float]] = {}

    async def add(self, loop: OpenLoop) -> str:
        self._loops[loop.id] = loop
        return loop.id

    async def add_unique(self, loop: OpenLoop) -> str | None:
        """같은 세션의 열린 같은 약속이 있으면 기한만 갱신하고, 바뀔 게 없으면 None 반환."""
        if not normalize_description(loop.description):
            return None
        candidates = await self._open_in_session(loop.origin_session)
        record = merge_loop(candidates, loop, await self._similarities(loop, candidates))
        return await self.add(record) if record is not None else None

    async def _open_in_session(self, session_id: str | None) -> list[OpenLoop]:
        return [x for x in self._loops.values() if x.status == "open" and x.origin_session == session_id]

    async def _similarities(self, loop: OpenLoop, candidates: list[OpenLoop]) -> dict[str, float] | None:
        """새 약속과 후보들의 임베딩 코사인. 임베딩을 못 하면 None 이라 판정은 글자 겹침으로만 한다."""
        if self._embedder is None or not candidates:
            return None
        texts = [loop.description, *(c.description for c in candidates)]
        missing = list(dict.fromkeys(t for t in texts if t not in self._vectors))
        if missing:
            try:
                fresh = await self._embedder.embed(missing)
            except Exception:
                return None
            self._vectors.update(zip(missing, fresh, strict=False))
        # ponytail: 벡터는 프로세스 메모리에만 있어 재시작 뒤 첫 판정은 다시 임베딩한다, 그 비용이 보이면 레코드에 저장
        for text in texts:
            if text in self._vectors:
                self._vectors[text] = self._vectors.pop(text)  # 방금 쓴 것을 뒤로
        while len(self._vectors) > VECTOR_CACHE_MAX:
            del self._vectors[next(iter(self._vectors))]
        query = self._vectors.get(loop.description)
        if query is None:
            return None
        return {c.id: cosine(query, self._vectors[c.description]) for c in candidates if c.description in self._vectors}

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

    async def list_closed(self, limit: int = 20) -> list[OpenLoop]:
        """닫힌 항목을 마지막으로 바뀐 순으로. 잘못 닫힌 약속을 되살리는 화면이 쓴다."""
        # ponytail: 전부 읽어 고른다(약속은 하루 몇 건), 쌓여 느려지면 저장소마다 updated_at 순 조회로 바꾼다
        items = [x for x in await self.all() if x.status != "open"]
        items.sort(key=lambda x: x.updated_at, reverse=True)
        return items[:limit]


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
