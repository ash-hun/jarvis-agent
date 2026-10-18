"""[memory] 사용자가 조용할 때 daemon 틱에 얹혀 활성 세션들의 consolidate 를 돈다(수면 중 재생 자리)."""

import functools
from typing import TYPE_CHECKING, Any
from collections.abc import Awaitable, Callable, Iterable

if TYPE_CHECKING:
    from jarvis.memory.memory_service import MemoryService

Target = Callable[[], Awaitable[object]]


# sessions 는 UI 마다 다른 세션 객체라 memory_scope, is_running 을 덕 타이핑으로 읽는다
def consolidation_targets(
    memory: "MemoryService", sessions: Iterable[Any], idle_for: float, idle_sec: float
) -> list[Target]:
    """daemon 틱에 넣을 세션별 consolidate 콜러블.

    사용자가 idle_sec 넘게 조용할 때만 낸다. 트리거 종류와 상관없이 대화 중에는 추출 LLM 호출이 끼어들지 않는다.
    실행 중인 세션은 건너뛴다. observe 가 작업 기억을 저장하는 사이에 되뇌기를 비우면 횟수가 샌다.
    consolidate 는 멱등이라 다음 틱에 다시 돌면 된다.
    """
    if idle_for < idle_sec:
        return []
    return [
        functools.partial(memory.consolidate, session.memory_scope)
        for session in sessions
        if hasattr(session, "memory_scope") and not getattr(session, "is_running", False)
    ]
