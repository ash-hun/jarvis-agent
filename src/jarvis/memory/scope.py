"""메모리 범위. 누가(user), 어느 에이전트에서(agent), 어느 세션에서(session) 기억하는지."""

from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any

MAIN_AGENT = "main"
SHARED = "shared"
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

    def can_read(self, item_scope: "MemoryScope", visibility: str) -> bool:
        """장기 기억 읽기 상속 규칙.

        같은 사용자의 항목(또는 사용자가 없는 전역 항목) 중, 내 에이전트가 쓴 것이거나
        shared 로 표시된 것만 보인다. 다른 에이전트의 private 항목은 보이지 않는다.
        """
        if item_scope.user_id is not None and item_scope.user_id != self.user_id:
            return False
        return item_scope.agent_id == self.agent_id or visibility == SHARED

    def same_working_set(self, other: "MemoryScope") -> bool:
        """작업 기억(STM)은 상속 없이 (user, agent, session) 완전 일치만 같은 집합이다."""
        return self == other


def scope_from_context(context: dict[str, Any]) -> MemoryScope:
    """harness 가 미들웨어에 넘기는 context(session_id, user_id, agent_id)에서 범위를 조립한다."""
    return MemoryScope(
        user_id=context.get("user_id") or LOCAL_USER,
        agent_id=context.get("agent_id") or MAIN_AGENT,
        session_id=context.get("session_id"),
    )


# 턴 바깥에서 쓰는 경로(슬래시 명령, 사고 로그, 저널)가 현재 사용자를 알 수 있게 하는 통로.
# AgentSession.prompt 와 web 핸들러가 설정한다. 없으면 LOCAL_USER 의 메인 범위로 본다.
# ponytail: 전역 contextvar, 디스패처가 사용자를 인자로 받게 되면 제거
current_scope: ContextVar[MemoryScope | None] = ContextVar("jarvis_memory_scope", default=None)
