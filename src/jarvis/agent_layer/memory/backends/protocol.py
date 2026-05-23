from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from jarvis.model_layer.types import Message


@dataclass
class MemoryEntry:
    """장기 메모리 단위. 알고리즘과 스토리지에 독립적인 순수 데이터 객체."""

    content: str
    source: str  # "explicit" | "auto_summary" | "session_end"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


@runtime_checkable
class STMBackend(Protocol):
    """
    단기 메모리 백엔드 Protocol (세션 범위).

    구현체 교체 기준:
    - SQLite  → 기본 로컬 persistent 저장
    - Redis   → 멀티프로세스 공유 필요 시
    - in_memory → 테스트 / stateless 환경
    """

    async def load(self, session_id: str) -> list[Message]:
        """세션의 전체 메시지 이력을 순서대로 반환."""
        ...

    async def append(self, session_id: str, message: Message) -> None:
        """세션에 메시지 한 개를 추가."""
        ...

    async def clear(self, session_id: str) -> None:
        """세션의 모든 메시지를 삭제."""
        ...


@runtime_checkable
class LTMBackend(Protocol):
    """
    장기 메모리 백엔드 Protocol (세션 횡단).

    구현체 교체 기준:
    - SQLite  → 기본 키워드 검색
    - pgvector / Chroma → 의미론적 유사도 검색 필요 시
    - Elasticsearch     → 전문 검색 필요 시
    """

    async def store(self, entry: MemoryEntry) -> str:
        """항목을 저장하고 entry_id를 반환."""
        ...

    async def search(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        """키워드 또는 의미론적 검색으로 관련 항목을 반환."""
        ...

    async def get_recent(self, limit: int = 10) -> list[MemoryEntry]:
        """최근 저장된 항목을 반환 (최신순)."""
        ...

    async def delete(self, entry_id: str) -> None:
        """특정 항목을 삭제."""
        ...

    async def clear_all(self) -> None:
        """모든 장기 메모리를 삭제."""
        ...
