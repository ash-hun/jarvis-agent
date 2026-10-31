"""[memory] 세션 이력의 사본이 아니라 이력 위에 얹는 작업 기억 상태와, 그 상태를 dict 로 드는 저장소 기반 클래스."""

from datetime import datetime
from dataclasses import dataclass, field, replace

from jarvis.memory.scope import MemoryScope

MAX_NOTES = 50


@dataclass
class WorkingState:
    scope: MemoryScope
    rehearsal: dict[str, int] = field(default_factory=dict)  # 회상된 장기 기억 id → 참조 횟수
    notes: list[str] = field(default_factory=list)  # 세션 범위 메모(사고 흐름 등)
    updated_at: datetime = field(default_factory=datetime.now)

    def add_note(self, text: str) -> None:
        self.notes.append(text)
        del self.notes[:-MAX_NOTES]

    def rehearse(self, item_id: str) -> int:
        self.rehearsal[item_id] = self.rehearsal.get(item_id, 0) + 1
        return self.rehearsal[item_id]


class WorkingStore:
    """작업 기억 저장소. 기본 동작은 프로세스 메모리의 dict 이고, 영속 저장소는 메서드를 덮어쓴다."""

    def __init__(self) -> None:
        self._states: dict[MemoryScope, WorkingState] = {}

    async def load(self, scope: MemoryScope) -> WorkingState:
        """없으면 빈 상태를 돌려준다. 저장은 save 가 한다."""
        state = self._states.get(scope)
        if state is None:
            return WorkingState(scope=scope)
        # 호출자가 고친 뒤 save 하지 않으면 반영되지 않도록 사본을 준다
        return _copy(state)

    async def save(self, state: WorkingState) -> None:
        self._states[state.scope] = _copy(state)

    async def clear(self, scope: MemoryScope) -> None:
        self._states.pop(scope, None)

    async def delete_sessions(self, prefixes: tuple[str, ...], dry_run: bool = False) -> int:
        """세션 id 가 이 접두어로 시작하는 작업 기억을 지우고 수를 돌려준다. dry_run 이면 세기만 한다."""
        doomed = [s for s in self._states if prefixes and (s.session_id or "").startswith(prefixes)]
        if not dry_run:
            for scope in doomed:
                del self._states[scope]
        return len(doomed)

    async def delete_session(self, session_id: str) -> int:
        """세션 id 가 정확히 같은 작업 기억만 지운다(에이전트가 여럿이면 여러 행)."""
        doomed = [s for s in self._states if s.session_id == session_id]
        for scope in doomed:
            del self._states[scope]
        return len(doomed)

    async def legacy_stm_rows(self) -> int | None:
        """범위 도입 전 STM 메시지 테이블의 행 수. 그런 테이블을 모르는 저장소는 None."""
        return None

    async def drop_legacy_stm(self) -> None:
        """옛 STM 테이블 삭제. 모르는 저장소에는 지울 것이 없다."""
        return None


def _copy(state: WorkingState) -> WorkingState:
    return replace(state, rehearsal=dict(state.rehearsal), notes=list(state.notes))
