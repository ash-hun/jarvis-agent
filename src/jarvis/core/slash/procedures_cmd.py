"""[core] 학습된 절차를 나열, 승인, 삭제하고 세션에서 새로 학습하는 /procedures 핸들러 factory."""

from typing import TYPE_CHECKING
from collections.abc import Awaitable, Callable

from jarvis.core.procedures.tool import register_procedure, unregister_procedure
from jarvis.core.procedures.store import STATUS_APPROVED, ProcedureStore

if TYPE_CHECKING:
    from jarvis.agent_layer.session.protocol import SessionRepo
    from jarvis.core.procedures.learner import ProcedureLearner
    from jarvis.core.skills.registry import SkillRegistry
    from jarvis.core.tools.registry import ToolRegistry

Handler = Callable[[str], Awaitable[str]]

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
    session_id: str = DEFAULT_SESSION,
) -> Handler:
    async def handle(args: str) -> str:
        parts = args.strip().split(None, 1)
        sub = parts[0].lower() if parts else "list"
        rest = parts[1].strip() if len(parts) > 1 else ""

        if sub == "list":
            procedures = store.list()
            if not procedures:
                return (
                    "[Procedures] 학습된 절차가 없습니다. "
                    "도구를 여러 번 쓴 작업이 성공으로 끝나면 세션 종료 때 초안이 생깁니다."
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
            p = store.get(rest)
            if p is None:
                return f"[Procedures] 없는 절차: {rest}"
            return f"[Procedures] {p.name} [{p.status}] 출처 {p.source or '-'}\n{p.description}\n\n{p.body}"

        if sub == "approve":
            if not rest:
                return USAGE
            p = store.set_status(rest, STATUS_APPROVED)
            if p is None:
                return f"[Procedures] 없는 절차: {rest}"
            register_procedure(p, tool_registry, skill_registry)
            return f"[Procedures] 승인: {p.name} → 도구 procedure_{p.name}, 스킬 /{p.name}"

        if sub in ("reject", "forget"):
            if not rest:
                return USAGE
            if not store.delete(rest):
                return f"[Procedures] 없는 절차: {rest}"
            unregister_procedure(rest, tool_registry, skill_registry)
            return f"[Procedures] 삭제: {rest}"

        if sub == "learn":
            if learner is None or session_repo is None:
                return "[Procedures] 학습기가 꺼져 있습니다 (JARVIS_PROCEDURES__ENABLED)."
            target = rest or session_id
            messages = await session_repo.get_messages(target)
            written = await learner.learn(target, messages)
            if not written:
                return f"[Procedures] '{target}' 에서 새로 배울 구간이 없습니다 (이미 배웠거나, 호출이 적거나, 오류)."
            return "[Procedures] 초안 저장: " + ", ".join(written) + "\n승인: /procedures approve <name>"

        return USAGE

    return handle
