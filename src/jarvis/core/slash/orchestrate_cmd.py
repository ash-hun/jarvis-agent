"""[core] 사용자가 패턴과 참여 에이전트를 직접 지정해 오케스트레이션을 돌리는 /orchestrate 핸들러 factory."""

from typing import TYPE_CHECKING
from collections.abc import Awaitable, Callable

if TYPE_CHECKING:
    from jarvis.core.multi_agent.multi_agent_service import OrchestrationService
    from jarvis.core.slash.dispatcher import ScopedHandler
    from jarvis.memory.scope import MemoryScope

Handler = Callable[[str], Awaitable[str]]

_USAGE = (
    "[Orchestrate] 사용법:\n"
    "  /orchestrate <pattern> [--agents a,b] [--promote] <작업>\n"
    "  /orchestrate list        패턴과 에이전트 목록\n"
    "  pattern: supervisor | hierarchical | market | blackboard (쉼표로 이으면 파이프라인)"
)


def parse_args(args: str) -> tuple[str, list[str] | None, bool, str]:
    """'blackboard --agents a,b --promote 시장 분석' → (pattern, agents, promote, task)."""
    parts = args.split()
    if not parts:
        raise ValueError(_USAGE)
    pattern = parts[0].lower()
    agents: list[str] | None = None
    promote = False
    rest: list[str] = []
    i = 1
    while i < len(parts):
        token = parts[i]
        if token == "--promote":
            promote = True
        elif token == "--agents" and i + 1 < len(parts):
            agents = [a for a in parts[i + 1].split(",") if a]
            i += 1
        else:
            rest.append(token)
        i += 1
    task = " ".join(rest).strip()
    if not task:
        raise ValueError("[Orchestrate] 작업 내용이 비었습니다.\n" + _USAGE)
    return pattern, agents, promote, task


def make_orchestrate_handler(service: "OrchestrationService") -> "ScopedHandler":
    async def handle(args: str, scope: "MemoryScope") -> str:
        args = args.strip()
        if not args or args.lower() in ("help", "?"):
            return _USAGE
        if args.lower() == "list":
            lines = ["[Orchestrate] 패턴:"]
            lines += [f"  {name}: {desc}" for name, desc in service.patterns.items()]
            lines.append("에이전트:")
            lines += [
                f"  {d.name} (level {d.level}, {', '.join(d.capabilities) or 'general'}): {d.description}"
                for d in service.definitions
            ] or ["  (없음) agents_dir 에 YAML 정의를 추가하세요"]
            return "\n".join(lines)
        try:
            pattern, agents, promote, task = parse_args(args)
            result = await service.run(pattern, task, agents=agents, promote=promote, parent_scope=scope)
        except ValueError as exc:
            return str(exc) if str(exc).startswith("[Orchestrate]") else f"[Orchestrate] {exc}"
        if not result.success:
            return f"[Orchestrate] {pattern} 실패: {result.error}"
        return f"[Orchestrate] {pattern} 완료 ({result.agent_name})\n\n{result.content}"

    return handle
