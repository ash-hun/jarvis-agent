"""[ui] ChatHistory: TUI 채팅 영역에 역할별 색으로 줄을 쓴다."""

from __future__ import annotations

from rich.markup import escape as markup_escape
from textual.widgets import RichLog


class ChatHistory(RichLog):
    DEFAULT_CSS = "ChatHistory { border: solid $primary; height: 1fr; margin: 0; }"

    def add_user(self, text: str) -> None:
        self.write(f"[bold cyan]You:[/bold cyan] {markup_escape(text)}")

    def add_assistant(self, text: str) -> None:
        self.write(f"[bold green]Jarvis:[/bold green] {markup_escape(text)}")

    def add_tool(self, name: str, is_error: bool = False) -> None:
        color = "red" if is_error else "yellow"
        self.write(f"[{color}]  ⛙ {markup_escape(name)}[/{color}]")

    def add_status(self, text: str) -> None:
        self.write(f"[dim]{markup_escape(text)}[/dim]")

    def add_error(self, text: str) -> None:
        self.write(f"[bold red]Error:[/bold red] {markup_escape(text)}")

    def add_inner_thought(self, text: str) -> None:
        """inner thought(메타인지) — 메인 응답과 구분된 흐릿한 사고 라인."""
        self.write(f"[dim italic]💭 {markup_escape(text)}[/dim italic]")

    def add_proactive(self, text: str, msg_kind: str = "proactive") -> None:
        """시스템 비요청 발화 — filler(💬 대기) / proactive·answer(🔔 먼저 건넨 말)."""
        icon = "💬" if msg_kind == "filler" else "🔔"
        self.write(f"[bold magenta]{icon} Jarvis:[/bold magenta] {markup_escape(text)}")
