"""[core] 지금 에이전트의 작업 패턴(사용자가 알려 준 방식)을 보고 지우는 /patterns 핸들러 factory."""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.memory.memory_service import MemoryService

Handler = Callable[[str], Awaitable[str]]

USAGE = (
    "[Patterns] 사용법:\n"
    "  /patterns                 지금 에이전트의 작업 패턴 목록\n"
    "  /patterns forget <이름>    그 패턴 지우기"
)


def make_patterns_handler(memory: "MemoryService") -> Handler:
    async def handle(args: str) -> str:
        args = args.strip()
        if args.startswith("forget"):
            name = args[len("forget"):].strip()
            if not name:
                return USAGE
            removed = await memory.forget_pattern(name)
            if not removed:
                return f"[Patterns] '{name}' 이라는 패턴이 없습니다."
            return f"[Patterns] '{name}' 을 지웠습니다."
        if args:
            return USAGE
        patterns = await memory.task_patterns()
        if not patterns:
            return "[Patterns] 저장된 작업 패턴이 없습니다. 작업 방식을 알려 주고 기억해 달라고 하면 저장됩니다."
        lines = ["[Patterns] 이 에이전트의 작업 패턴:"]
        for p in patterns:
            keywords = ", ".join(p.keywords)
            lines.append(f"  - {p.name}\n    언제: {p.when}\n    어떻게: {p.steps}\n    키워드: {keywords}")
        return "\n".join(lines)

    return handle
