"""[core] 명령을 친 에이전트의 절차와 초안을 나열, 승인, 거절하고 세션에서 새로 학습하는 /procedures 핸들러 factory."""

from typing import TYPE_CHECKING
from collections.abc import Awaitable, Callable

from jarvis.core.procedures.procedures_store import KIND_TASK_PATTERN, Procedure, ProcedureStore
from jarvis.core.procedures.tool import owner_of, register_procedure, unregister_procedure
from jarvis.memory.long_term.task_pattern import TaskPattern, normalize_keywords
from jarvis.core.procedures.learner import PATTERN_PREFIX

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

    async def approve_pattern(draft: Procedure, scope: "MemoryScope") -> str:
        """작업 패턴 초안은 메모리의 작업 패턴으로 옮기고 파일은 지운다. 같은 이름이면 메모리가 덮는다."""
        memory = learner.memory if learner is not None else None
        if memory is None:
            return "[Procedures] 작업 패턴은 메모리가 켜져 있어야 승인할 수 있습니다."
        name = draft.name.removeprefix(PATTERN_PREFIX)
        pattern = TaskPattern(name, draft.description, draft.body.strip(), normalize_keywords(list(draft.keywords)))
        await memory.remember_pattern(pattern, scope=scope)
        store.delete(draft.name)
        return f"[Procedures] 작업 패턴으로 승인: {name} (키워드 {', '.join(pattern.keywords)})"

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
                    "[Procedures] 학습된 절차가 없습니다. 같은 종류의 작업이 3번 성공하거나 도구 작업이 실패하면"
                    " 통합(세션 종료, 유휴) 때 초안이 생깁니다."
                )
            lines = ["[Procedures] 학습된 절차와 초안:"]
            for proc in procedures:
                lines.append(f"  {'✓' if proc.approved else '·'} {proc.name} [{_label(proc)}] {proc.description}")
            lines.append(
                "승인: /procedures approve <name>  (절차는 procedure_<name> 도구와 /<name> 스킬이 되고,"
                " 개정 초안은 본문을 바꾸고, 작업 패턴 초안은 이 에이전트의 작업 패턴이 된다)"
            )
            return "\n".join(lines)

        if sub == "show":
            if not rest:
                return USAGE
            p = own(rest)
            if p is None:
                return f"[Procedures] 없는 절차: {rest}"
            text = f"[Procedures] {p.name} [{_label(p)}] 출처 {p.source or '-'}\n{p.description}\n\n{p.body}"
            if p.keywords:
                text += f"키워드: {', '.join(p.keywords)}\n"
            if p.revision is not None:
                text += f"\n[개정 초안] {p.revision.description}\n\n{p.revision.body}"
            return text

        if sub == "approve":
            if not rest:
                return USAGE
            current = own(rest)
            if current is None:
                return f"[Procedures] 없는 절차: {rest}"
            if current.kind == KIND_TASK_PATTERN:
                return await approve_pattern(current, scope)
            revised = current.revision is not None
            p = store.approve(rest)
            if p is None:
                return f"[Procedures] 없는 절차: {rest}"
            # 도구 레지스트리는 first-wins 라 옛 본문을 내리고 다시 올린다
            unregister_procedure(p.name, tool_registry, skill_registry)
            register_procedure(p, tool_registry, skill_registry)
            what = "개정으로 교체" if revised else "승인"
            return f"[Procedures] {what}: {p.name} → 도구 procedure_{p.name}, 스킬 /{p.name}"

        if sub in ("reject", "forget"):
            if not rest:
                return USAGE
            current = own(rest)
            if current is not None and current.revision is not None and sub == "reject":
                store.drop_revision(rest)
                return f"[Procedures] 개정 초안 버림: {rest} (승인된 본문은 그대로)"
            if current is None or not store.delete(rest):
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


def _label(p: Procedure) -> str:
    """상태 옆에 초안 종류를 붙인다. 승인된 절차에 개정이 기다리면 함께 적는다."""
    if p.kind == KIND_TASK_PATTERN:
        return f"{p.status}, 작업 패턴"
    return f"{p.status}, 개정 초안 있음" if p.revision is not None else p.status
