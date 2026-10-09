from __future__ import annotations

import asyncio
import contextlib
from typing import Protocol, runtime_checkable

from jarvis.agent_layer.thought.types import ThoughtFrame
from jarvis.memory.manager import MemoryManager

# 사고 로그를 식별하는 태그. 회상 시 일반 기억과 구분/필터하는 데 쓴다.
THOUGHT_SOURCE = "thought"


@runtime_checkable
class ThoughtSink(Protocol):
    """`ThoughtFrame`을 어딘가에 영속화하는 교체 가능한 싱크."""

    async def store(self, frame: ThoughtFrame, session_id: str | None = None) -> None: ...


class LTMThoughtSink:
    """LTM(세션 횡단)에 프레임 전체를 JSON으로 저장. `source="thought"` 태깅."""

    def __init__(self, memory: MemoryManager) -> None:
        self._memory = memory

    async def store(self, frame: ThoughtFrame, session_id: str | None = None) -> None:
        scope = self._memory.resolve_scope().with_session(session_id)
        await self._memory.remember(
            frame.model_dump_json(),
            source=THOUGHT_SOURCE,
            scope=scope,
            tags=[f"decision:{frame.decision}"],
            metadata={"decision": frame.decision, "confidence": frame.confidence},
        )


class WorkingNotesSink:
    """작업 기억(세션 범위)의 메모에 사고를 한 줄로 남긴다. 대화 컨텍스트에는 들어가지 않는다."""

    def __init__(self, memory: MemoryManager) -> None:
        self._memory = memory

    async def store(self, frame: ThoughtFrame, session_id: str | None = None) -> None:
        summary = frame.interpretation or frame.observation
        scope = self._memory.resolve_scope().with_session(session_id or "default")
        await self._memory.add_note(f"[{THOUGHT_SOURCE}:{frame.decision}] {summary}", scope=scope)


class ThoughtLog:
    """여러 `ThoughtSink`로 사고를 fan-out하는 오케스트레이터.

    저장은 부가 작업이므로 싱크별 실패를 격리해 예외를 전파하지 않는다(메인 턴 보호).
    """

    def __init__(self, sinks: list[ThoughtSink]) -> None:
        self._sinks = sinks

    async def store(self, frame: ThoughtFrame, session_id: str | None = None) -> None:
        async def _safe(sink: ThoughtSink) -> None:
            with contextlib.suppress(Exception):
                await sink.store(frame, session_id)

        await asyncio.gather(*[_safe(s) for s in self._sinks])
