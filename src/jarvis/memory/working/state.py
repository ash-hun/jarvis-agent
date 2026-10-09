"""작업 기억 상태와 저장소 프로토콜. 세션 이력의 사본이 아니라 이력 위에 얹는 메타데이터다."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from jarvis.memory.scope import MemoryScope

MAX_NOTES = 50


@dataclass
class WorkingState:
    scope: MemoryScope
    summary: str | None = None  # 컴팩션 결과. 다음 턴은 이 요약 + 덮이지 않은 꼬리만 본다
    summary_covers: int = 0  # session_repo 이력에서 요약이 대체한 앞부분 메시지 수
    rehearsal: dict[str, int] = field(default_factory=dict)  # 회상된 장기 기억 id → 참조 횟수
    notes: list[str] = field(default_factory=list)  # 세션 범위 메모(사고 흐름 등)
    updated_at: datetime = field(default_factory=datetime.now)

    def add_note(self, text: str) -> None:
        self.notes.append(text)
        del self.notes[:-MAX_NOTES]

    def rehearse(self, item_id: str) -> int:
        self.rehearsal[item_id] = self.rehearsal.get(item_id, 0) + 1
        return self.rehearsal[item_id]


@runtime_checkable
class WorkingStore(Protocol):
    async def load(self, scope: MemoryScope) -> WorkingState:
        """없으면 빈 상태를 돌려준다. 저장은 save 가 한다."""
        ...

    async def save(self, state: WorkingState) -> None: ...

    async def clear(self, scope: MemoryScope) -> None: ...
