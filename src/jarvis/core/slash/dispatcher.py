from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from jarvis.core.scheduler.service import SchedulerService

# /command at start-of-string or after whitespace.
# Negative lookbehind (?<!\S) prevents matching paths inside URLs (http://host/path).
_CMD_RE = re.compile(r"(?<!\S)/([a-zA-Z?][a-zA-Z0-9_-]*)")

Handler = Callable[[str], Awaitable[str]]


@dataclass
class ParseResult:
    """Slash command 파싱 결과."""

    remaining_text: str
    feedbacks: list[str] = field(default_factory=list)

    @property
    def fully_consumed(self) -> bool:
        """slash command만 있고 LLM으로 전달할 텍스트가 없음."""
        return not self.remaining_text.strip() and bool(self.feedbacks)


class SlashCommandDispatcher:
    """
    텍스트 어디서나 /command 패턴을 감지해 슬래시 명령을 처리한다.
    새 명령은 register()로 동적 추가 가능.
    """

    def __init__(self, scheduler: SchedulerService | None = None) -> None:
        self._handlers: dict[str, Handler] = {}
        self._descriptions: dict[str, str] = {}
        self._register_builtins(scheduler)

    def register(self, name: str, handler: Handler, description: str = "") -> None:
        """새 슬래시 명령을 등록한다."""
        self._handlers[name.lower()] = handler
        self._descriptions[name.lower()] = description

    @property
    def commands(self) -> dict[str, str]:
        """등록된 명령 이름 → 설명 딕셔너리 (? alias 제외)."""
        return {k: v for k, v in self._descriptions.items() if k != "?"}

    async def dispatch(self, text: str) -> ParseResult:
        """
        텍스트에서 /command 패턴을 모두 추출·실행한다.
        반환값: ParseResult(remaining_text=LLM 전달용 텍스트, feedbacks=명령 실행 메시지 목록)
        slash command가 없으면 feedbacks가 비어 있고 remaining_text == text.
        """
        remaining, commands = self._extract_commands(text)
        if not commands:
            return ParseResult(remaining_text=text)

        feedbacks: list[str] = []
        for cmd_name, args in commands:
            handler = self._handlers.get(cmd_name.lower())
            if handler is None:
                feedbacks.append(f"알 수 없는 명령: /{cmd_name}\n\n{self._help_text()}")
            else:
                feedbacks.append(await handler(args))

        return ParseResult(remaining_text=remaining, feedbacks=feedbacks)

    # ── 내부 유틸 ──────────────────────────────────────────────────────────────

    def _extract_commands(self, text: str) -> tuple[str, list[tuple[str, str]]]:
        """
        텍스트에서 /command 위치를 모두 찾고 (remaining_text, [(name, args), ...]) 반환.
        각 명령의 args = 명령어 이름 끝 ~ 다음 명령어 시작(또는 줄 끝).
        """
        matches = list(_CMD_RE.finditer(text))
        if not matches:
            return text, []

        commands: list[tuple[str, str]] = []
        remaining_parts: list[str] = []
        prev_end = 0

        for i, m in enumerate(matches):
            remaining_parts.append(text[prev_end : m.start()])

            cmd_name_end = m.end()
            if i + 1 < len(matches):
                next_start = matches[i + 1].start()
                line_end = text.find("\n", cmd_name_end)
                # 같은 줄 안에 다음 명령이 있으면 줄 끝을 기준으로 분리
                args_end = line_end if 0 <= line_end < next_start else next_start
            else:
                line_end = text.find("\n", cmd_name_end)
                args_end = line_end if line_end != -1 else len(text)

            args = text[cmd_name_end:args_end].strip()
            commands.append((m.group(1), args))
            prev_end = args_end

        remaining_parts.append(text[prev_end:])
        remaining = "".join(remaining_parts).strip()
        return remaining, commands

    def _register_builtins(self, scheduler: SchedulerService | None) -> None:
        from jarvis.core.slash.schedule_cmd import make_schedule_handler

        self.register(
            "schedule",
            make_schedule_handler(scheduler),
            "YYYY.MM.DD 오전/오후 N시까지 <프롬프트>",
        )
        self.register("help", self._handle_help, "사용 가능한 명령 목록 표시")
        self.register("?", self._handle_help, "")  # alias, help text에서 생략

    async def _handle_help(self, _args: str) -> str:
        return self._help_text()

    def _help_text(self) -> str:
        lines = ["사용 가능한 슬래시 명령:"]
        for name in sorted(self._descriptions):
            if name == "?":
                continue
            desc = self._descriptions[name]
            lines.append(f"  /{name}" + (f"  — {desc}" if desc else ""))
        lines += [
            "",
            "예시:",
            "  /schedule 2026.06.01 오전 9시까지 웹검색으로 AI 트렌드 자료 수집해줘",
            "  /schedule 2026.06.01 09:00까지 매일 날씨를 확인하고 기록해줘",
        ]
        return "\n".join(lines)
