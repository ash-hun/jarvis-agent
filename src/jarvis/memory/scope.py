"""[memory] 누가(user), 어느 에이전트에서(agent), 어느 세션에서(session) 기억하는지 정하는 메모리 범위와 읽기 규칙."""

from typing import Any
from contextvars import ContextVar
from dataclasses import dataclass, replace

MAIN_AGENT = "main"
SHARED = "shared"
PRIVATE = "private"
# 인증이 없는 TUI 와 열린 web 모드의 사용자 id. NoAuthAuthenticator 와 같은 값이어야
# 턴 안에서 읽는 scope 와 슬래시 명령이 쓰는 scope 가 일치한다.
LOCAL_USER = "local"


@dataclass(frozen=True)
class MemoryScope:
    user_id: str | None  # None 은 전역 항목(범위 도입 전 레거시 행). 읽는 주체는 항상 값이 있다
    agent_id: str = MAIN_AGENT
    session_id: str | None = None

    def child(self, agent_id: str, session_id: str) -> "MemoryScope":
        """서브 에이전트에 위임할 때 만드는 자식 범위. 사용자는 상속하고 에이전트와 세션은 새로 받는다."""
        return MemoryScope(user_id=self.user_id, agent_id=agent_id, session_id=session_id)

    def with_session(self, session_id: str | None) -> "MemoryScope":
        return replace(self, session_id=session_id)

    def same_working_set(self, other: "MemoryScope") -> bool:
        """작업 기억(STM)은 상속 없이 (user, agent, session) 완전 일치만 같은 집합이다."""
        return self == other


def scope_from_context(context: dict[str, Any]) -> MemoryScope:
    """harness 와 사고 엔진이 넘기는 context(session_id, user_id, agent_id)에서 범위를 조립한다.

    비운 값은 로컬 사용자와 main 에이전트다. 호출자가 범위를 다 넘겨야 다른 사용자의 기억을 읽지 않는다.
    """
    return MemoryScope(
        user_id=context.get("user_id") or LOCAL_USER,
        agent_id=context.get("agent_id") or MAIN_AGENT,
        session_id=context.get("session_id"),
    )


# 오케스트레이션 작업 범위. 한 작업에 참여하는 에이전트들이 공유하는 작업 기억의 키(루트 task_id).
# LazyAgentNode 가 위임 동안 설정하고, observe 가 읽어 [작업 공유 메모리] 블록을 넣는다.
current_task: ContextVar[str | None] = ContextVar("jarvis_memory_task", default=None)
TASK_AGENT = "task"


def task_scope(user_id: str | None, root_task_id: str) -> MemoryScope:
    """작업 공유 메모리의 범위. 참여 에이전트와 무관하게 (사용자, 작업) 으로만 정해진다."""
    return MemoryScope(user_id=user_id or LOCAL_USER, agent_id=TASK_AGENT, session_id=f"task_{root_task_id}")
