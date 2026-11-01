"""[core] 명령을 친 에이전트의 절차를 나열, 승인, 삭제하고 세션에서 새로 학습하는 /procedures 핸들러 factory."""

from typing import TYPE_CHECKING
from collections.abc import Awaitable, Callable

from jarvis.core.procedures.procedures_store import STATUS_APPROVED, Procedure, ProcedureStore
from jarvis.core.procedures.tool import owner_of, register_procedure, unregister_procedure

if TYPE_CHECKING:
    from jarvis.agent_layer.session.session_protocol import SessionRepo
    from jarvis.core.skills.skills_registry import SkillRegistry
    from jarvis.core.procedures.learner import ProcedureLearner
    from jarvis.core.tools.tools_registry import ToolRegistry
    from jarvis.memory.scope import MemoryScope

ScopedHandler = Callable[[str, "MemoryScope"], Awaitable[str]]

USAGE = (
    "[Procedures] 사용법: /procedures [list] | show <name> | approve <name> | reject <name> | learn [session_id]"
)
DEFAULT_SESSION = "default"


def make_procedures_handler(
    store: ProcedureStore,
    tool_registry: "ToolRegistry",
    skill_registry: "SkillRegistry",
    learner: "ProcedureLearner | None" = None,
    session_repo: "SessionRepo | None" = None,
) -> ScopedHandler:
    """scope 의 에이전트가 배운 절차만 다룬다. 다른 에이전트의 절차는 없는 것처럼 보인다."""

    async def handle(args: str, scope: "MemoryScope") -> str:
        parts = args.strip().split(None, 1)
        sub = parts[0].lower() if parts else "list"
        rest = parts[1].strip() if len(parts) > 1 else ""
        agent = scope.agent_id

        def own(name: str) -> Procedure | None:
            p = store.get(name)
            return p if p is not None and owner_of(p) == agent else None

        if sub == "list":
            procedures = [p for p in store.list() if owner_of(p) == agent]
            if not procedures:
                return (
                    "[Procedures] 학습된 절차가 없습니다. "
                    "같은 종류의 작업이 3번 성공하면 통합(세션 종료, 유휴) 때 초안이 생깁니다."
                )
            lines = ["[Procedures] 학습된 절차:"]
            for proc in procedures:
                mark = "✓" if proc.approved else "·"
                lines.append(f"  {mark} {proc.name} [{proc.status}] {proc.description}")
            lines.append("승인: /procedures approve <name>  (승인하면 procedure_<name> 도구와 /<name> 스킬이 된다)")
            return "\n".join(lines)

        if sub == "show":
            if not rest:
                return USAGE
            p = own(rest)
            if p is None:
                return f"[Procedures] 없는 절차: {rest}"
            return f"[Procedures] {p.name} [{p.status}] 출처 {p.source or '-'}\n{p.description}\n\n{p.body}"

        if sub == "approve":
            if not rest:
                return USAGE
            p = store.set_status(rest, STATUS_APPROVED) if own(rest) is not None else None
            if p is None:
                return f"[Procedures] 없는 절차: {rest}"
            register_procedure(p, tool_registry, skill_registry)
            return f"[Procedures] 승인: {p.name} → 도구 procedure_{p.name}, 스킬 /{p.name}"

        if sub in ("reject", "forget"):
            if not rest:
                return USAGE
            if own(rest) is None or not store.delete(rest):
                return f"[Procedures] 없는 절차: {rest}"
            unregister_procedure(rest, tool_registry, skill_registry)
            return f"[Procedures] 삭제: {rest}"

        if sub == "learn":
            if learner is None or session_repo is None:
                return "[Procedures] 학습기가 꺼져 있습니다 (JARVIS_PROCEDURES__ENABLED)."
            target = rest or scope.session_id or DEFAULT_SESSION
            messages = await session_repo.get_messages(target)
            written = await learner.learn(target, messages, agent=agent)
            if not written:
                return f"[Procedures] '{target}' 에서 새로 배울 구간이 없습니다 (이미 배웠거나, 호출이 적거나, 오류)."
            return "[Procedures] 초안 저장: " + ", ".join(written) + "\n승인: /procedures approve <name>"

        return USAGE

    return handle
