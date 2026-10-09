from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label

# dismiss 값. True/False 는 이번 한 번, "always" 는 제안된 패턴을 승인 규칙으로 남긴다.
ALWAYS = "always"


class ApprovalDialog(ModalScreen[bool | str]):
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
    ApprovalDialog #hint {
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("y", "allow", "Allow", show=False),
        Binding("a", "always", "Always", show=False),
        Binding("n", "deny", "Deny", show=False),
        Binding("escape", "deny", "Deny", show=False),
    ]

    def __init__(self, command: str, reason: str, always_pattern: str = "") -> None:
        super().__init__()
        self._command = command
        self._reason = reason
        self._always_pattern = always_pattern

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"[bold yellow]Approval Required[/bold yellow]\n{self._reason}")
            yield Label(
                f"[dim]{self._command[:300]}[/dim]",
                id="command-preview",
            )
            hint = "  y  Allow    n / Esc  Deny"
            if self._always_pattern:
                hint += f"    a  Always allow '{self._always_pattern}'"
            yield Label(f"[dim]{hint}[/dim]", id="hint")
            with Horizontal():
                yield Button("Allow (y)", variant="warning", id="allow")
                if self._always_pattern:
                    yield Button("Always (a)", variant="primary", id="always")
                yield Button("Deny (n)", variant="error", id="deny")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "always":
            self.dismiss(ALWAYS)
        else:
            self.dismiss(event.button.id == "allow")

    def action_allow(self) -> None:
        self.dismiss(True)

    def action_always(self) -> None:
        # 패턴이 없으면 "항상"의 대상이 없다. 이번 한 번 허용으로 떨어진다
        self.dismiss(ALWAYS if self._always_pattern else True)

    def action_deny(self) -> None:
        self.dismiss(False)
