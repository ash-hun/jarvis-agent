"""[core] 지금 세션의 에이전트에게 목표를 맡기고, 보고, 멈추는 /goal 핸들러 factory."""

from typing import TYPE_CHECKING
from collections.abc import Awaitable, Callable

if TYPE_CHECKING:
    from jarvis.core.goals.tool import GoalTool
    from jarvis.memory.scope import MemoryScope

ScopedHandler = Callable[[str, "MemoryScope"], Awaitable[str]]

USAGE = (
    "[Goal] 사용법:\n"
    "  /goal                 맡은 목표 목록\n"
    "  /goal <목표 문장>      목표 맡기기(같은 문장은 하나로 남는다)\n"
    "  /goal stop <문장 일부>  목표 멈추기"
)


def make_goal_handler(tool: "GoalTool") -> ScopedHandler:
    """말로 맡기면 모델이 그 자리에서 한 번 찾고 끝내기도 한다(실측). 이 명령은 모델 없이 맡긴다."""

    async def handle(args: str, scope: "MemoryScope") -> str:
        agent = scope.agent_id
        text = " ".join(args.split())
        if not text:
            return "[Goal] " + tool.list_goals(agent)
        if text in ("help", "-h"):
            return USAGE
        sub, _, rest = text.partition(" ")
        if sub == "stop":
            return "[Goal] " + tool.stop_goal(agent, rest) if rest else USAGE
        return "[Goal] " + tool.set_goal(agent, text).split(". 이번 답에서는")[0]

    return handle
