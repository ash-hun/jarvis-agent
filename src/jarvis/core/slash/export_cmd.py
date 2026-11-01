"""[core] 현재 세션 대화를 markdown 또는 json 파일로 내보내는 /export 핸들러 factory."""

import re
import json
from pathlib import Path
from typing import TYPE_CHECKING
from collections.abc import Awaitable, Callable

if TYPE_CHECKING:
    from jarvis.agent_layer.session.session_protocol import SessionRepo
    from jarvis.model_layer.model_types import Message
    from jarvis.memory.scope import MemoryScope

DEFAULT_SESSION_ID = "default"
# 세션 id 는 웹 쿼리에서 그대로 온다. 파일명에 쓰기 전에 경로 문자를 지운다
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9_-]")

ScopedHandler = Callable[[str, "MemoryScope"], Awaitable[str]]

_USAGE = (
    "[Export] 사용법: /export [md|json]\n"
    "  md   — 마크다운 (기본)\n"
    "  json — 원본 메시지 JSON"
)


def _text_of(content: object) -> str:
    """메시지 content(str | block 리스트)를 평문으로 변환."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content if isinstance(content, list) else []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts)


def conversation_to_markdown(messages: "list[Message]", session_id: str) -> str:
    """메시지 목록을 사람이 읽기 좋은 마크다운으로 변환."""
    lines = [f"# Jarvis 대화 — {session_id}", ""]
    for msg in messages:
        role = getattr(msg, "role", "")
        if role == "user":
            lines.append("## 🧑 User")
            lines.append(_text_of(msg.content))
        elif role == "assistant":
            model = getattr(msg, "model", "") or ""
            header = f"## 🤖 Assistant{f' ({model})' if model else ''}"
            lines.append(header)
            text = msg.text() if hasattr(msg, "text") else _text_of(msg.content)
            lines.append(text)
            for tc in (msg.tool_calls() if hasattr(msg, "tool_calls") else []):
                lines.append(f"\n> 🔧 tool call: `{tc.name}`")
        elif role == "tool_result":
            status = "error" if getattr(msg, "is_error", False) else "ok"
            lines.append(f"### 🔧 Tool result: {getattr(msg, 'tool_name', '')} [{status}]")
            lines.append("```")
            lines.append(_text_of(msg.content))
            lines.append("```")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def conversation_to_json(messages: "list[Message]", session_id: str) -> str:
    """메시지 목록을 원본 구조 그대로 JSON 직렬화."""
    payload = {
        "session_id": session_id,
        "message_count": len(messages),
        "messages": [json.loads(m.model_dump_json()) for m in messages],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def make_export_handler(
    session_repo: "SessionRepo",
    export_dir: str = "~/.jarvis/exports",
) -> ScopedHandler:
    """/export 핸들러 factory. 명령을 친 세션 대화를 파일로 저장."""

    async def handle(args: str, scope: "MemoryScope") -> str:
        fmt = (args.strip() or "md").lower()
        if fmt not in ("md", "markdown", "json"):
            return _USAGE
        session_id = scope.session_id or DEFAULT_SESSION_ID

        messages = await session_repo.get_messages(session_id)
        if not messages:
            return "[Export] 내보낼 대화가 없습니다."

        if fmt == "json":
            content = conversation_to_json(messages, session_id)
            ext = "json"
        else:
            content = conversation_to_markdown(messages, session_id)
            ext = "md"

        out_dir = Path(export_dir).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{_UNSAFE_FILENAME.sub('_', session_id)}.{ext}"
        path.write_text(content, encoding="utf-8")

        return f"[Export] 대화를 내보냈습니다: {path} ({len(messages)}개 메시지)"

    return handle
