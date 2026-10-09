"""/cleanup. 범위 도입 전 남은 데이터를 보여주고, 확인어가 있을 때만 지운다. 자동으로는 절대 지우지 않는다."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jarvis.agent_layer.session.protocol import SessionRepo

Handler = Callable[[str], Awaitable[str]]
CONFIRM = "confirm"
# 범위 도입 전 서브 에이전트 세션 이름. 지금은 agent_<name>__<parent> 라 '__' 가 없는 것이 옛것이다.
# memory.stm = per_agent 정책을 쓰는 에이전트도 같은 이름을 쓰므로, 그 경우엔 지우지 않는다.
LEGACY_AGENT_SESSION = re.compile(r"^agent_[^_]+$")

_USAGE = (
    "[Cleanup] 사용법:\n"
    "  /cleanup                 지울 수 있는 옛 데이터 현황\n"
    "  /cleanup agents confirm  범위 도입 전 서브 에이전트 세션(agent_<name>) 삭제\n"
    "  /cleanup stm confirm     옛 STM 메시지 테이블(jarvis_stm_messages) 삭제 (Postgres)"
)


def make_cleanup_handler(
    session_repo: SessionRepo,
    memory: Any = None,
    keep_agent_sessions: set[str] | None = None,
) -> Handler:
    """keep_agent_sessions: per_agent 정책 에이전트의 세션 id. 이름이 옛 형식과 같아도 보존한다."""
    keep = keep_agent_sessions or set()

    async def legacy_sessions() -> list[str]:
        metas = await session_repo.list("")
        return sorted(
            m.session_id for m in metas if LEGACY_AGENT_SESSION.match(m.session_id) and m.session_id not in keep
        )

    async def handle(args: str) -> str:
        parts = args.split()
        if not parts:
            sessions = await legacy_sessions()
            stm_rows = await memory.legacy_stm_rows() if memory is not None else None
            lines = ["[Cleanup] 옛 데이터 현황:"]
            preview = f" ({', '.join(sessions[:5])}…)" if sessions else ""
            lines.append(f"  서브 에이전트 세션(옛 형식): {len(sessions)}개{preview}")
            if stm_rows is None:
                lines.append("  옛 STM 테이블: 없음 또는 Postgres 아님")
            else:
                lines.append(f"  옛 STM 테이블 jarvis_stm_messages: {stm_rows}행")
            lines.append("삭제는 '/cleanup agents confirm' 또는 '/cleanup stm confirm'")
            return "\n".join(lines)

        target = parts[0].lower()
        confirmed = len(parts) > 1 and parts[1].lower() == CONFIRM
        if target == "agents":
            sessions = await legacy_sessions()
            if not sessions:
                return "[Cleanup] 지울 옛 서브 에이전트 세션이 없습니다."
            if not confirmed:
                return f"[Cleanup] {len(sessions)}개 세션을 지우려면 '/cleanup agents confirm' 으로 확인하세요."
            for sid in sessions:
                await session_repo.delete(sid)
            return f"[Cleanup] 서브 에이전트 세션 {len(sessions)}개를 지웠습니다."
        if target == "stm":
            if memory is None:
                return "[Cleanup] 메모리 매니저가 없습니다."
            rows = await memory.legacy_stm_rows()
            if rows is None:
                return "[Cleanup] 옛 STM 테이블이 없거나 Postgres 가 아닙니다."
            if not confirmed:
                return f"[Cleanup] jarvis_stm_messages {rows}행을 지우려면 '/cleanup stm confirm' 으로 확인하세요."
            await memory.drop_legacy_stm()
            return f"[Cleanup] jarvis_stm_messages 테이블({rows}행)을 지웠습니다."
        return _USAGE

    return handle
