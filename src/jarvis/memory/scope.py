"""메모리 범위. 누가(user), 어느 에이전트에서(agent), 어느 세션에서(session) 기억하는지."""

from dataclasses import dataclass

MAIN_AGENT = "main"
SHARED = "shared"


@dataclass(frozen=True)
class MemoryScope:
    user_id: str
    agent_id: str = MAIN_AGENT
    session_id: str | None = None

    def child(self, agent_id: str, session_id: str) -> "MemoryScope":
        """서브 에이전트에 위임할 때 만드는 자식 범위. 사용자는 상속하고 에이전트와 세션은 새로 받는다."""
        return MemoryScope(user_id=self.user_id, agent_id=agent_id, session_id=session_id)

    def can_read(self, item_scope: "MemoryScope", visibility: str) -> bool:
        """장기 기억 읽기 상속 규칙.

        같은 사용자의 항목 중, 내 에이전트가 쓴 것이거나 shared 로 표시된 것만 보인다.
        다른 에이전트의 private 항목은 보이지 않는다.
        """
        if item_scope.user_id != self.user_id:
            return False
        return item_scope.agent_id == self.agent_id or visibility == SHARED

    def same_working_set(self, other: "MemoryScope") -> bool:
        """작업 기억(STM)은 상속 없이 (user, agent, session) 완전 일치만 같은 집합이다."""
        return self == other
