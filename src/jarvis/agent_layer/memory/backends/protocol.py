from __future__ import annotations

from typing import Protocol, runtime_checkable

from jarvis.model_layer.types import Message


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
