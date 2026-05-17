from __future__ import annotations

from textual.widgets import RichLog


class ChatHistory(RichLog):
    DEFAULT_CSS = "ChatHistory { border: solid $primary; height: 1fr; margin: 0; }"

    def add_user(self, text: str) -> None:
        self.write(f"[bold cyan]You:[/bold cyan] {text}")

    def add_assistant(self, text: str) -> None:
        self.write(f"[bold green]Jarvis:[/bold green] {text}")

    def add_tool(self, name: str, is_error: bool = False) -> None:
        color = "red" if is_error else "yellow"
        self.write(f"[{color}]  ⛙ {name}[/{color}]")

    def add_status(self, text: str) -> None:
        self.write(f"[dim]{text}[/dim]")

    def add_error(self, text: str) -> None:
        self.write(f"[bold red]Error:[/bold red] {text}")
