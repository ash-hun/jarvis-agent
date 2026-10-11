"""[memory] 사용자가 조용할 때 daemon 틱에 얹혀 활성 세션들의 consolidate 를 돈다(수면 중 재생 자리)."""

import functools
from collections.abc import Awaitable, Callable, Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jarvis.config import JarvisSettings
    from jarvis.memory.memory_service import MemoryService

Target = Callable[[], Awaitable[object]]


def should_consolidate_on_idle(settings: "JarvisSettings") -> bool:
    """interval 트리거만 켜져 있으면 대화 중에도 틱이 와서 LLM 호출이 끼어든다. idle 또는 both 일 때만."""
    return settings.memory.consolidate_on_idle and settings.proactive.daemon_trigger != "interval"


# sessions 는 UI 마다 다른 세션 객체라 memory_scope, is_running 을 덕 타이핑으로 읽는다
def consolidation_targets(memory: "MemoryService", sessions: Iterable[Any]) -> list[Target]:
    """daemon 틱에 넣을 세션별 consolidate 콜러블.

    실행 중인 세션은 건너뛴다. observe 가 작업 기억을 저장하는 사이에 되뇌기를 비우면 횟수가 샌다.
    consolidate 는 멱등이라 다음 틱에 다시 돌면 된다.
    """
    return [
        functools.partial(memory.consolidate, session.memory_scope)
        for session in sessions
        if hasattr(session, "memory_scope") and not getattr(session, "is_running", False)
    ]
