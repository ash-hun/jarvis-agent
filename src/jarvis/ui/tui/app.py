from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import Reactive
from textual.widgets import Footer, Header, Input

from jarvis.agent_layer.types import AgentEvent
from jarvis.core.session import AgentSession
from jarvis.ui.tui.bridge import (
    AppendStreamAction,
    EventBridge,
    FlushStreamAction,
    ShowErrorAction,
    ShowStatusAction,
    ToolEndAction,
    ToolStartAction,
    UIAction,
)
from jarvis.ui.tui.components.approval_dialog import ApprovalDialog
from jarvis.ui.tui.components.chat_history import ChatHistory
from jarvis.ui.tui.components.sidebar import SidebarPane
from jarvis.ui.tui.components.status_bar import StatusBar
from jarvis.ui.tui.state import ActiveTool

if TYPE_CHECKING:
    from jarvis.ui.tui.startup import AppContext


class JarvisTUI(App[None]):
    """
    Jarvis 터미널 UI — Textual 기반.

    Warp: Entity-Handle 패턴
    - App이 모든 위젯을 소유 (compose()에서 한 번만 생성)
    - 핸들은 on_mount()에서 단 한 번 확정
    - 이벤트 핸들러에서 위젯 인라인 생성 금지

    Hunk: Session Bridge + Split 레이아웃
    """

    CSS = """
    Screen { layout: vertical; }

    #body {
        height: 1fr;
        layout: horizontal;
    }

    #main-pane {
        width: 1fr;
        layout: vertical;
    }

    Input {
        dock: bottom;
        margin: 0 1 1 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+k", "abort", "Abort", show=True),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar", show=True),
        Binding("ctrl+n", "new_session", "New Session", show=True),
    ]

    # Reactive 상태 — App 소유 (Warp: Entity 패턴)
    is_streaming: Reactive[bool] = Reactive(False)
    active_tool_count: Reactive[int] = Reactive(0)
    sidebar_visible: Reactive[bool] = Reactive(True)

    def __init__(
        self,
        session: AgentSession,
        ctx: AppContext,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._session = session
        self._ctx = ctx  # Warp: ctx, 마지막 파라미터

        # 한 번만 생성 (Warp: MouseStateHandle 원칙)
        self._bridge = EventBridge()

        # 내부 상태 (순수 Python, Textual 독립)
        self._stream_buffer = ""
        self._active_tools: list[ActiveTool] = []

        # 위젯 핸들 선언 — on_mount()에서 확정 (Warp: ViewHandle 패턴)
        self._chat: ChatHistory | None = None
        self._sidebar: SidebarPane | None = None
        self._status: StatusBar | None = None
        self._input: Input | None = None

        session.subscribe(self._on_agent_event)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield SidebarPane(id="sidebar")
            with Vertical(id="main-pane"):
                yield ChatHistory(id="chat", markup=True, highlight=True, wrap=True)
        yield Input(
            placeholder="Type your message... (Ctrl+K abort, Ctrl+B sidebar)",
            id="input",
        )
        yield StatusBar(id="status")
        yield Footer()

    async def on_mount(self) -> None:
        # 핸들 한 번에 확정 (Warp: mount 시 단일 생성 원칙)
        self._chat = self.query_one("#chat", ChatHistory)
        self._sidebar = self.query_one("#sidebar", SidebarPane)
        self._status = self.query_one("#status", StatusBar)
        self._input = self.query_one("#input", Input)

        # 사이드바 초기 데이터 로딩
        await self._sidebar.load_sessions(self._ctx.session_repo)
        self._sidebar.load_tools(self._ctx.tool_registry)

        self._chat.write("[bold]Jarvis ready.[/bold] Type a message to begin.")
        self._input.focus()

    # ── 입력 처리 ─────────────────────────────────────────────────────────────

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return

        assert self._input is not None
        assert self._chat is not None

        self._input.value = ""

        if text == "/exit":
            self.exit()
            return

        self._input.disabled = True
        self._chat.add_user(text)
        self._stream_buffer = ""

        asyncio.create_task(self._run_prompt(text))

    async def _run_prompt(self, text: str) -> None:
        assert self._input is not None
        assert self._chat is not None
        try:
            await self._session.prompt(text)
        except Exception as exc:
            self._chat.add_error(str(exc))
        finally:
            self._input.disabled = False
            self._input.focus()

    # ── EventBridge 적용 (Hunk: Session Bridge 패턴) ─────────────────────────

    async def _on_agent_event(self, event: AgentEvent) -> None:
        if self._chat is None:
            return  # on_mount 전 안전 가드
        try:
            for action in self._bridge.translate(event):
                await self._apply_action(action)
        except Exception as exc:
            self._chat.add_error(f"[internal] {exc}")

    async def _apply_action(self, action: UIAction) -> None:
        if self._chat is None or self._status is None:
            return

        match action:
            case ShowStatusAction(text=t):
                self._status.set_status(t)

            case AppendStreamAction(delta=d):
                self._stream_buffer += d
                self.is_streaming = True

            case FlushStreamAction():
                if self._stream_buffer:
                    self._chat.add_assistant(self._stream_buffer)
                    self._stream_buffer = ""
                self.is_streaming = False

            case ToolStartAction(tool_call_id=tid, tool_name=n):
                self._active_tools.append(ActiveTool(tool_call_id=tid, tool_name=n, started_at=int(time.time() * 1000)))
                self._chat.add_tool(f"Running {n}...")
                self.active_tool_count = len(self._active_tools)

            case ToolEndAction(tool_call_id=tid, tool_name=n, is_error=err):
                self._active_tools = [t for t in self._active_tools if t.tool_call_id != tid]
                self._chat.add_tool(f"{n} [{'error' if err else 'done'}]", err)
                self.active_tool_count = len(self._active_tools)

            case ShowErrorAction(message=m):
                self._chat.add_error(m)

    # ── UIAdapter.request_approval 구현 ───────────────────────────────────────

    async def request_approval(self, command: str, reason: str) -> bool:
        """ApprovalDialog 모달을 표시하고 사용자 결정을 반환."""
        result: bool = await self.push_screen_wait(ApprovalDialog(command=command, reason=reason))
        return result

    # ── 액션 ──────────────────────────────────────────────────────────────────

    def action_abort(self) -> None:
        self._session.abort()

    def action_toggle_sidebar(self) -> None:
        """사이드바 토글 (Hunk: layout toggle 패턴)."""
        self.sidebar_visible = not self.sidebar_visible
        sidebar = self.query_one("#sidebar", SidebarPane)
        sidebar.display = self.sidebar_visible

    async def action_new_session(self) -> None:
        """Ctrl+N: 새 UUID 세션을 생성하고 대화를 초기화한다."""
        if self._ctx.session_factory is None:
            return

        assert self._chat is not None
        assert self._status is not None
        assert self._input is not None

        self._status.set_status("Creating new session...")
        self._input.disabled = True

        try:
            new_session = await self._ctx.session_factory()
            new_session.subscribe(self._on_agent_event)
            self._session = new_session
            self._stream_buffer = ""
            self._active_tools = []
            self.is_streaming = False
            self.active_tool_count = 0

            self._chat.clear()
            self._chat.write(
                f"[bold]New session:[/bold] [dim]{new_session._session_id}[/dim]"
            )
            assert self._sidebar is not None
            await self._sidebar.load_sessions(self._ctx.session_repo)
            self._status.set_status("Ready")
        except Exception as exc:
            self._chat.add_error(f"Failed to create session: {exc}")
            self._status.set_status("Ready")
        finally:
            self._input.disabled = False
            self._input.focus()


def main() -> None:
    from jarvis.ui.tui.startup import main as startup_main

    startup_main()


if __name__ == "__main__":
    main()
