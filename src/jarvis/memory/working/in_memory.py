"""테스트와 in_memory 설정용 작업 기억 저장소."""

from dataclasses import replace

from jarvis.memory.scope import MemoryScope
from jarvis.memory.working.state import WorkingState


class InMemoryWorkingStore:
    def __init__(self) -> None:
        self._states: dict[MemoryScope, WorkingState] = {}

    async def load(self, scope: MemoryScope) -> WorkingState:
        state = self._states.get(scope)
        if state is None:
            return WorkingState(scope=scope)
        # 호출자가 고친 뒤 save 하지 않으면 반영되지 않도록 사본을 준다
        return replace(state, rehearsal=dict(state.rehearsal), notes=list(state.notes))

    async def save(self, state: WorkingState) -> None:
        self._states[state.scope] = replace(state, rehearsal=dict(state.rehearsal), notes=list(state.notes))

    async def clear(self, scope: MemoryScope) -> None:
        self._states.pop(scope, None)
