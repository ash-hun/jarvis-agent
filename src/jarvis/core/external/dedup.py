from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import aiofiles

from jarvis.core.external.types import ExternalEvent

# 아이템 목록이 들어있을 법한 필드 이름(벤더 공통 관례). 첫 list 필드를 쓴다.
_LIST_FIELDS = ("items", "events", "messages", "results", "data")
# 아이템의 안정적 식별자 후보. 있으면 텍스트 해시보다 우선한다.
_ID_FIELDS = ("id", "uid", "eventId", "messageId", "threadId")
_TITLE_FIELDS = ("title", "summary", "subject", "name", "description")
_TIME_FIELDS = ("start", "date", "datetime", "occurred_at", "created", "timestamp", "receivedAt")


def derive_events(source: str, raw: str, *, detail_max_chars: int = 500) -> list[ExternalEvent]:
    """MCP 툴 원문 응답 → ExternalEvent 목록. 벤더 파서 없이 관례만 이용한다."""
    events: list[ExternalEvent] = []
    for item in _split_items(raw):
        detail = _canonical_text(item)
        if not detail.strip():
            continue
        events.append(
            ExternalEvent(
                source=source,
                key=_item_key(source, item),
                title=_item_title(item),
                detail=detail[:detail_max_chars],
                occurred_at=_item_time(item),
            )
        )
    return events


def _split_items(raw: str) -> list[Any]:
    """원문을 아이템 단위로 쪼갠다. 실패하면 전체를 1건으로 본다."""
    text = (raw or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return [text]

    if isinstance(payload, list):
        return list(payload)
    if isinstance(payload, dict):
        for field in _LIST_FIELDS:
            value = payload.get(field)
            if isinstance(value, list):
                return list(value)
        return [payload]
    return [text]


def _item_key(source: str, item: Any) -> str:
    if isinstance(item, dict):
        for field in _ID_FIELDS:
            value = item.get(field)
            if isinstance(value, str | int) and str(value).strip():
                return f"{source}:{value}"
    digest = hashlib.sha1(_canonical_text(item).encode("utf-8")).hexdigest()[:16]
    return f"{source}:{digest}"


def _item_title(item: Any) -> str:
    if isinstance(item, dict):
        for field in _TITLE_FIELDS:
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _item_time(item: Any) -> str:
    if isinstance(item, dict):
        for field in _TIME_FIELDS:
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
            # {"start": {"dateTime": "..."}} 같은 중첩 형태도 best-effort로 집는다.
            if isinstance(value, dict):
                for nested in ("dateTime", "date", "value"):
                    inner = value.get(nested)
                    if isinstance(inner, str) and inner.strip():
                        return inner.strip()
    return ""


def _canonical_text(item: Any) -> str:
    if isinstance(item, str):
        return item
    try:
        return json.dumps(item, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(item)


@runtime_checkable
class SeenStore(Protocol):
    """이미 본 이벤트 키를 기억해 재발화를 막는 저장소."""

    async def filter_new(self, events: list[ExternalEvent]) -> list[ExternalEvent]: ...


class InMemorySeenStore:
    """휘발성 dedup 저장소 — 테스트·일회성 운용."""

    def __init__(
        self,
        ttl_sec: float = 604_800.0,
        max_keys: int = 10_000,
        clock: Any = time.time,
    ) -> None:
        self._ttl = ttl_sec
        self._max_keys = max_keys
        self._clock = clock
        self._seen: dict[str, float] = {}

    async def filter_new(self, events: list[ExternalEvent]) -> list[ExternalEvent]:
        now = self._clock()
        self._prune(now)
        fresh: list[ExternalEvent] = []
        for event in events:
            if event.key in self._seen:
                continue
            self._seen[event.key] = now
            fresh.append(event)
        self._prune(now)
        return fresh

    def _prune(self, now: float) -> None:
        if self._ttl > 0:
            expired = [k for k, ts in self._seen.items() if now - ts > self._ttl]
            for key in expired:
                del self._seen[key]
        overflow = len(self._seen) - self._max_keys
        if overflow > 0:
            # 오래된 키부터 버린다(삽입 시각 기준).
            for key, _ in sorted(self._seen.items(), key=lambda kv: kv[1])[:overflow]:
                del self._seen[key]

    def __len__(self) -> int:
        return len(self._seen)


class JsonlSeenStore:
    """JSONL append-only dedup 저장소 (기본). JsonlOpenLoopStore와 동일한 영속 철학.

    로드 시 TTL 초과 키를 버리고 max_keys만 유지한다 — 무한 증식 방지.
    """

    def __init__(
        self,
        path: str = "~/.jarvis/external_seen.jsonl",
        ttl_sec: float = 604_800.0,
        max_keys: int = 10_000,
        clock: Any = time.time,
    ) -> None:
        self._path = Path(path).expanduser()
        self._ttl = ttl_sec
        self._max_keys = max_keys
        self._clock = clock
        self._seen: dict[str, float] = {}
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
                            record = json.loads(line)
                            key = record["key"]
                            ts = float(record.get("ts", 0.0))
                        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                            continue
                        self._seen[str(key)] = ts  # last-wins replay
            self._prune(self._clock())
            self._loaded = True

    async def filter_new(self, events: list[ExternalEvent]) -> list[ExternalEvent]:
        await self._ensure_loaded()
        now = self._clock()
        fresh: list[ExternalEvent] = []
        for event in events:
            if event.key in self._seen:
                continue
            self._seen[event.key] = now
            fresh.append(event)
        if fresh:
            await self._append(fresh, now)
        self._prune(now)
        return fresh

    async def _append(self, events: list[ExternalEvent], now: float) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lines = "".join(
            json.dumps({"key": e.key, "ts": now}, ensure_ascii=False) + "\n" for e in events
        )
        async with aiofiles.open(self._path, "a", encoding="utf-8") as f:
            await f.write(lines)

    def _prune(self, now: float) -> None:
        if self._ttl > 0:
            expired = [k for k, ts in self._seen.items() if now - ts > self._ttl]
            for key in expired:
                del self._seen[key]
        overflow = len(self._seen) - self._max_keys
        if overflow > 0:
            for key, _ in sorted(self._seen.items(), key=lambda kv: kv[1])[:overflow]:
                del self._seen[key]

    def __len__(self) -> int:
        return len(self._seen)
