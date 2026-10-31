"""[core] 운영용 슬래시 명령(/sessions, /branch, /tools, /compact) 핸들러 factory."""

from typing import TYPE_CHECKING
from collections.abc import Awaitable, Callable

if TYPE_CHECKING:
    from jarvis.agent_layer.session.session_protocol import SessionRepo
    from jarvis.core.tools.tools_registry import ToolRegistry
    from jarvis.memory.memory_service import MemoryService
    from jarvis.model_layer.model_types import ModelConfig
    from jarvis.memory.scope import MemoryScope

Handler = Callable[[str], Awaitable[str]]
ScopedHandler = Callable[[str, "MemoryScope"], Awaitable[str]]


def make_sessions_handler(session_repo: "SessionRepo") -> Handler:
    """/sessions: 저장된 세션 목록을 표시."""

    async def handle(_args: str) -> str:
        sessions = await session_repo.list("")
        if not sessions:
            return "[Sessions] 저장된 세션이 없습니다."
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        lines = ["[Sessions] 저장된 세션:"]
        for s in sessions:
            branch = f" ← {s.parent_id}" if s.parent_id else ""
            lines.append(f"  {s.session_id}  (메시지 {s.message_count}개){branch}")
        return "\n".join(lines)

    return handle


def make_branch_handler(session_repo: "SessionRepo", default_session_id: str = "default") -> Handler:
    """/branch [session_id]: 세션을 특정 시점에서 분기."""

    async def handle(args: str) -> str:
        parent_id = args.strip() or default_session_id
        existing = {s.session_id for s in await session_repo.list("")}
        if parent_id not in existing:
            return f"[Branch] 세션을 찾을 수 없습니다: {parent_id} (/sessions 로 확인)"
        try:
            meta = await session_repo.create_branch(parent_id)
        except Exception as exc:
            return f"[Branch] 분기 실패: {exc}"
        return (
            f"[Branch] '{parent_id}'에서 분기했습니다.\n"
            f"  새 세션: {meta.session_id} (메시지 {meta.message_count}개 복사)\n"
            f"  재개: jarvis -s {meta.session_id}"
        )

    return handle


def make_tools_handler(tool_registry: "ToolRegistry") -> Handler:
    """/tools: 현재 사용 가능한 도구 목록을 표시."""

    async def handle(_args: str) -> str:
        tools = sorted(tool_registry.list_all(), key=lambda t: t.name)
        if not tools:
            return "[Tools] 등록된 도구가 없습니다."
        lines = [f"[Tools] 사용 가능한 도구 ({len(tools)}개):"]
        for t in tools:
            desc = (t.description or "").split("\n", 1)[0]
            if len(desc) > 80:
                desc = desc[:77] + "..."
            lines.append(f"  {t.name}  — {desc}")
        return "\n".join(lines)

    return handle


def make_compact_handler(
    model: "ModelConfig",
    session_repo: "SessionRepo",
    memory: "MemoryService | None" = None,
) -> ScopedHandler:
    """/compact: 명령을 친 세션을 요약해 장기 기억(LTM)에 저장."""

    async def handle(_args: str, scope: "MemoryScope") -> str:
        session_id = scope.session_id or "default"
        messages = await session_repo.get_messages(session_id)
        if len(messages) < 2:
            return "[Compact] 요약할 대화 내용이 충분하지 않습니다."

        from jarvis.memory.consolidation import summarize_messages

        summary = await summarize_messages(model, messages)
        if summary is None:
            return "[Compact] 요약 모델 호출에 실패했습니다."

        if memory is not None:
            await memory.remember(summary, source="manual_compact", scope=scope.with_session(session_id))
            saved = " (장기 기억에 저장됨)"
        else:
            saved = ""

        preview = summary[:300] + ("..." if len(summary) > 300 else "")
        return f"[Compact] {len(messages)}개 메시지를 요약했습니다{saved}.\n\n{preview}"

    return handle
