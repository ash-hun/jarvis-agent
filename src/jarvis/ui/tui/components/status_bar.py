"""[ui] StatusBar: TUI 하단 상태 한 줄."""

from __future__ import annotations

from textual.widgets import Static


class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $primary-darken-1;
        color: $text;
        padding: 0 1;
    }
    """

    def on_mount(self) -> None:
        self.update(" Ready")

    def set_status(self, text: str) -> None:
        self.update(f" {text}")
