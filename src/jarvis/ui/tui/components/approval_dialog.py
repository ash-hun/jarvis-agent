from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ApprovalDialog(ModalScreen[bool]):
    """
    보안 파이프라인이 승인을 요청할 때 표시하는 모달.
    UIAdapter.request_approval() 구현체.
    """

    DEFAULT_CSS = """
    ApprovalDialog {
        align: center middle;
    }
    ApprovalDialog #dialog {
        width: 64;
        border: solid $warning;
        padding: 1 2;
        background: $surface;
    }
    ApprovalDialog #command-preview {
        color: $text-muted;
        margin: 1 0;
        overflow: hidden;
        max-height: 4;
    }
    ApprovalDialog Horizontal {
        height: auto;
        margin-top: 1;
        align: right middle;
    }
    ApprovalDialog Button {
        margin: 0 1;
    }
    """

    def __init__(self, command: str, reason: str) -> None:
        super().__init__()
        self._command = command
        self._reason = reason

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"[bold yellow]Approval Required[/bold yellow]\n{self._reason}")
            yield Label(
                f"[dim]{self._command[:300]}[/dim]",
                id="command-preview",
            )
            with Horizontal():
                yield Button("Allow", variant="warning", id="allow")
                yield Button("Deny", variant="error", id="deny")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "allow")
