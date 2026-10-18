"""[ui] AgentActivity: 지금 일하는 에이전트를 세션의 agent_start, agent_end 로 세고 바뀌면 열린 HUD 전부에 알린다."""

from typing import TYPE_CHECKING
from collections.abc import Awaitable, Callable

if TYPE_CHECKING:
    from jarvis.core.session import AgentSession

ACTIVITY_EVENT = "agent_activity"

Broadcast = Callable[[dict[str, object]], Awaitable[None]]


class AgentActivity:
    """세션 id → 에이전트 id 로 루프가 도는 세션을 들고 있다. 같은 에이전트의 세션이 여럿 돌아도 에이전트는 한 번 센다.

    루프 시작과 끝 사이에서 예외가 나면 끝 이벤트가 없어 그 세션이 계속 일하는 것으로 남는다.
    """

    def __init__(self, broadcast: Broadcast) -> None:
        self._broadcast = broadcast
        self._busy: dict[str, str] = {}

    def active(self) -> list[str]:
        """일하는 에이전트 id. 먼저 시작한 순서, 중복 없음."""
        return list(dict.fromkeys(self._busy.values()))

    def mark(self, session_id: str, agent_id: str, busy: bool) -> bool:
        """세션 하나의 상태를 바꾸고 에이전트 목록이 달라졌는지 돌려준다. 같은 값을 두 번 줘도 결과가 같다."""
        before = self.active()
        if busy:
            self._busy[session_id] = agent_id
        else:
            self._busy.pop(session_id, None)
        return self.active() != before

    def watch(self, session_id: str, agent_id: str, session: "AgentSession") -> None:
        """세션 이벤트를 구독한다. SessionRegistry 가 세션을 처음 열 때 한 번 부른다."""

        async def on_event(event: object) -> None:
            kind = getattr(event, "type", "")
            if kind not in ("agent_start", "agent_end"):
                return
            if self.mark(session_id, agent_id, kind == "agent_start"):
                await self._broadcast({"type": ACTIVITY_EVENT, "active": self.active()})

        session.subscribe(on_event)
