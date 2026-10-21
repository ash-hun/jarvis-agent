"""[ui] JarvisTUI: Textual 앱으로 채팅, 사이드바, 승인 모달, proactive daemon 을 묶는다."""

import re
import time
from textual.events import Key
from textual.binding import Binding
from textual.reactive import Reactive
from typing import TYPE_CHECKING, Any
from textual.app import App, ComposeResult
from collections.abc import Awaitable, Callable
from textual.widgets import Footer, Header, Input
from textual.containers import Horizontal, Vertical

from jarvis.ui.tui.bridge import (
    AgentPopAction,
    AgentPushAction,
    AppendStreamAction,
    EventBridge,
    FlushStreamAction,
    InnerThoughtAction,
    ProactiveMessageAction,
    ShowErrorAction,
    ShowStatusAction,
    ToolEndAction,
    ToolStartAction,
    UIAction,
)
from jarvis.ui.tui.components.approval_dialog import ApprovalDialog
from jarvis.ui.tui.components.chat_history import ChatHistory
from jarvis.ui.tui.components.slash_picker import SlashPicker
from jarvis.ui.tui.components.status_bar import StatusBar
from jarvis.ui.tui.components.sidebar import SidebarPane
from jarvis.agent_layer.types import AgentEvent
from jarvis.core.session import AgentSession
from jarvis.ui.tui.state import ActiveTool
from jarvis.ui.protocol import UIAdapter

if TYPE_CHECKING:
    from jarvis.core.proactive import ProactivityDaemon
    from jarvis.ui.tui.voice import TuiVoiceController
    from jarvis.app.app_context import AppContext


class JarvisTUI(App[None], UIAdapter):
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

    #chat {
        height: 1fr;
    }

    SlashPicker {
        display: none;
    }

    SlashPicker.-visible {
        display: block;
    }

    /* /command 입력 시 입력창 border를 cyan-bright로 강조 */
    Input.-slash-mode {
        border: tall $accent;
        color: $accent;
    }

    Input {
        margin: 0 1 1 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+k", "abort", "Abort", show=True),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar", show=True),
        Binding("ctrl+n", "new_session", "New Session", show=True),
        Binding("ctrl+f", "fork_session", "Fork Session", show=True),
        Binding("ctrl+t", "toggle_speak", "Speak", show=True),
        Binding("ctrl+r", "voice_input", "Voice", show=True),
        Binding("ctrl+y", "proactive_accept", "👍 Proactive", show=False),
        Binding("ctrl+g", "proactive_dismiss", "👎 Proactive", show=False),
        Binding("down", "picker_down", "Picker", show=False),
        Binding("up", "picker_up", "Picker Up", show=False),
        Binding("escape", "picker_close", "Close Picker", show=False),
    ]

    # Reactive 상태 — App 소유 (Warp: Entity 패턴)
    is_streaming: Reactive[bool] = Reactive(False)
    active_tool_count: Reactive[int] = Reactive(0)
    sidebar_visible: Reactive[bool] = Reactive(True)
    speak_mode: Reactive[bool] = Reactive(False)  # Ctrl+T: 응답 음성 출력 토글

    def __init__(
        self,
        session: AgentSession,
        ctx: "AppContext",
        voice_controller: "TuiVoiceController | None" = None,
        **kwargs: Any,  # Textual App 생성 인자(driver_class, css_path 등)를 그대로 넘긴다
    ) -> None:
        super().__init__(**kwargs)
        self._session = session
        self._ctx = ctx  # Warp: ctx, 마지막 파라미터
        # voice.tui_enabled 일 때만 진입점이 넘긴다
        self._voice_controller = voice_controller

        # 한 번만 생성 (Warp: MouseStateHandle 원칙)
        self._bridge = EventBridge()
        self._proactive_daemon: ProactivityDaemon | None = None  # on_mount에서 조건부 기동
        self._last_proactive_id: str | None = None  # 피드백(ctrl+y/g) 대상

        # 내부 상태 (순수 Python, Textual 독립)
        self._stream_buffer = ""
        self._active_tools: list[ActiveTool] = []
        self._agent_stack: list[str] = []  # 계층 추적: ["main", "researcher", ...]

        # 위젯 핸들 선언 — on_mount()에서 확정 (Warp: ViewHandle 패턴)
        self._chat: ChatHistory | None = None
        self._sidebar: SidebarPane | None = None
        self._status: StatusBar | None = None
        self._input: Input | None = None
        self._picker: SlashPicker | None = None

        # slash picker 상태 — 커서 기준 /command 시작 위치
        self._picker_slash_start: int = 0

        session.subscribe(self._on_agent_event)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield SidebarPane(id="sidebar")
            with Vertical(id="main-pane"):
                yield ChatHistory(id="chat", markup=True, highlight=True, wrap=True)
                yield SlashPicker(id="slash-picker")
                yield Input(
                    placeholder="Type your message... (/ command, ↑↓ picker, Tab complete, Ctrl+K abort)",
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
        self._picker = self.query_one("#slash-picker", SlashPicker)

        # 사이드바 초기 데이터 로딩
        await self._sidebar.load_sessions(self._ctx.session_repo)
        self._sidebar.load_tools(self._ctx.tool_registry)

        self._chat.write("[bold]Jarvis ready.[/bold] Type a message to begin.")
        self._input.focus()

        # 스케줄러 시작 (croniter 없으면 service 내부에서 skip)
        if self._ctx.scheduler is not None:
            self.run_worker(self._ctx.scheduler.start())

        # Proactivity Daemon (B3) — 요청 없이 주기적으로 성찰해 먼저 말 검.
        pcfg = self._ctx.settings.proactive
        if pcfg.daemon_enabled:
            from jarvis.memory.consolidation.idle import consolidation_targets
            from jarvis.core.proactive import ProactivityDaemon

            memory = self._ctx.memory
            clock = self._ctx.activity_clock
            consolidate = memory is not None and clock is not None and self._ctx.settings.memory.consolidate_on_idle

            # provider는 매 틱 self._session을 다시 읽어 세션 전환을 자동 추종.
            def targets() -> list[Callable[[], Awaitable[object]]]:
                reflects: list[Callable[[], Awaitable[object]]] = [self._session.reflect]
                # consolidate 가 참이면 memory, clock 은 None 이 아니다. 클로저 안이라 mypy 가 좁히지 못해 다시 적는다
                if not consolidate or memory is None or clock is None:
                    return reflects
                idle_for = clock.idle_seconds()
                return reflects + consolidation_targets(memory, [self._session], idle_for, pcfg.daemon_idle_sec)

            self._proactive_daemon = ProactivityDaemon(
                targets,
                interval_sec=pcfg.daemon_interval_sec,
                trigger=self._ctx.reflection_trigger,
            )
            self.run_worker(self._proactive_daemon.start())

        # 외부 이벤트 폴러(Phase 3) — daemon과 동일한 수명. 소스가 없으면 None.
        if self._ctx.external_poller is not None:
            self.run_worker(self._ctx.external_poller.start())

    async def on_unmount(self) -> None:
        if self._proactive_daemon is not None:
            await self._proactive_daemon.stop()
        if self._ctx.external_poller is not None:
            await self._ctx.external_poller.stop()

    # ── 슬래시 명령 picker ────────────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        """'/' 입력 시 picker를 표시하고, 그 외에는 숨긴다. 문장 중간도 감지."""
        if self._picker is None or self._input is None or self._ctx.dispatcher is None:
            return

        val = event.value
        m = re.search(r"(?:^|\s)(/([a-zA-Z0-9_?-]*))$", val)

        if m:
            self._picker_slash_start = m.start(1)
            query = m.group(2)
            self._picker.populate(self._ctx.dispatcher.commands, query=query)
            if self._picker.option_count > 0:
                self._picker.highlighted = 0
                self._picker.add_class("-visible")
                self._input.add_class("-slash-mode")
                return

        self._picker.remove_class("-visible")
        self._input.remove_class("-slash-mode")

    def _apply_picker_selection(self) -> None:
        """현재 picker에서 하이라이트된 옵션을 Input의 /fragment 위치에 삽입하고 picker를 닫는다."""
        if self._picker is None or self._input is None:
            return
        highlighted = self._picker.highlighted if self._picker.highlighted is not None else 0
        opt = self._picker.get_option_at_index(highlighted)
        if opt and opt.id:
            prefix = self._input.value[: self._picker_slash_start]
            self._input.value = f"{prefix}/{opt.id} "
            self._input.action_end()
        self._picker.remove_class("-visible")
        self._input.remove_class("-slash-mode")
        self._input.focus()

    def on_option_list_option_selected(self, event: SlashPicker.OptionSelected) -> None:
        """Enter/Space로 picker 항목 선택 시 /fragment를 명령어로 교체한다."""
        if self._picker is None or self._input is None:
            return
        if event.option.id:
            prefix = self._input.value[: self._picker_slash_start]
            self._input.value = f"{prefix}/{event.option.id} "
            self._input.action_end()
        self._picker.remove_class("-visible")
        self._input.remove_class("-slash-mode")
        self._input.focus()

    def action_picker_down(self) -> None:
        """↓ 키: picker가 열려 있으면 picker로 포커스 이동."""
        if self._picker is None:
            return
        if self._picker.has_class("-visible"):
            self._picker.focus()

    def action_picker_up(self) -> None:
        """↑ 키: picker가 열려 있으면 마지막 항목으로 포커스 이동."""
        if self._picker is None:
            return
        if self._picker.has_class("-visible"):
            self._picker.highlighted = self._picker.option_count - 1
            self._picker.focus()

    def action_picker_close(self) -> None:
        """Escape: picker를 닫고 Input으로 복귀."""
        if self._picker is None or self._input is None:
            return
        self._picker.remove_class("-visible")
        self._input.remove_class("-slash-mode")
        self._input.focus()

    def on_key(self, event: Key) -> None:
        """Tab: picker가 열려 있고 input에 포커스일 때 현재 항목 완성."""
        if event.key != "tab":
            return
        if self._picker is None or self._input is None:
            return
        if self._picker.has_class("-visible") and self._input.has_focus:
            event.prevent_default()
            self._apply_picker_selection()

    # ── 입력 처리 ─────────────────────────────────────────────────────────────

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        # picker가 열려 있으면 Enter로 항목 선택 (제출 대신)
        if self._picker is not None and self._picker.has_class("-visible"):
            self._apply_picker_selection()
            return

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

        # 슬래시 명령 인터셉트 — 텍스트 어디서나 /command 처리 후 나머지만 LLM으로 전달
        if self._ctx.dispatcher is not None:
            result = await self._ctx.dispatcher.dispatch(text, self._session.memory_scope)
            for feedback in result.feedbacks:
                self._chat.add_assistant(feedback)
            if result.fully_consumed:
                self._input.disabled = False
                self._input.focus()
                return
            text = result.remaining_text

        if not text.strip():
            self._input.disabled = False
            self._input.focus()
            return

        self.run_worker(self._run_prompt(text))

    async def _run_prompt(self, text: str) -> None:
        if self._input is None or self._chat is None:
            return
        try:
            await self._session.prompt(text)
        except Exception as exc:
            if self._chat is not None:
                self._chat.add_error(str(exc))
        finally:
            if self._input is not None:
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
                    spoken = self._stream_buffer
                    self._chat.add_assistant(spoken)
                    self._stream_buffer = ""
                    if self.speak_mode and self._voice_controller is not None:
                        self.run_worker(self._speak(spoken))
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

            case InnerThoughtAction(interpretation=interp, decision=dec, confidence=conf):
                if interp:
                    self._chat.add_inner_thought(f"{interp}  ({dec} · {conf:.0%})")

            case ProactiveMessageAction(text=ptext, msg_kind=mk, speak=spk, message_id=mid):
                # 뒤로 넘긴 작업의 답은 스트림으로 이미 그렸다. answer 는 외부 채널용이다
                if ptext and mk != "answer":
                    self._chat.add_proactive(ptext, mk)
                    # filler가 아닌 먼저 건넨 말은 피드백 대상으로 기록 (ctrl+y/ctrl+g).
                    if mk != "filler" and mid:
                        self._last_proactive_id = mid
                        self._chat.add_status("ctrl+y 도움됨 / ctrl+g 무시")
                    # voice 모드면 비요청 발화도 즉시 읽어준다(filler는 특히 중요).
                    if (spk or self.speak_mode) and self._voice_controller is not None:
                        self.run_worker(self._speak(ptext))

            case AgentPushAction(agent_name=name):
                self._agent_stack.append(name)
                breadcrumb = " → ".join(self._agent_stack)
                self._status.set_status(f"Thinking… [{breadcrumb}]")

            case AgentPopAction():
                if self._agent_stack:
                    self._agent_stack.pop()
                if self._agent_stack:
                    breadcrumb = " → ".join(self._agent_stack)
                    self._status.set_status(f"Thinking… [{breadcrumb}]")
                else:
                    self._status.set_status("Ready")

    # ── UIAdapter 구현 ────────────────────────────────────────────────────────

    async def on_agent_event(self, event: AgentEvent) -> None:
        """UIAdapter 구현 — session.subscribe 경로와 동일."""
        await self._on_agent_event(event)

    async def on_stream_text(self, delta: str) -> None:
        """UIAdapter 구현 — 스트림 델타를 버퍼에 누적."""
        self._stream_buffer += delta
        self.is_streaming = True

    async def show_error(self, error: str) -> None:
        """UIAdapter 구현 — 에러 메시지를 채팅 영역에 표시."""
        if self._chat is not None:
            self._chat.add_error(error)

    async def request_approval(self, command: str, reason: str, always_pattern: str = "") -> bool | str:
        """ApprovalDialog 모달을 표시하고 사용자 결정(True/False/"always")을 반환."""
        result: bool | str = await self.push_screen_wait(
            ApprovalDialog(command=command, reason=reason, always_pattern=always_pattern)
        )
        return result

    # ── 액션 ──────────────────────────────────────────────────────────────────

    def action_abort(self) -> None:
        self._session.abort()

    # ── 음성 (TUI) ────────────────────────────────────────────────────────────

    def action_toggle_speak(self) -> None:
        """Ctrl+T: 에이전트 응답 음성 출력(TTS) 토글."""
        vc = self._voice_controller
        if self._chat is None or self._status is None:
            return
        if vc is None:
            self._chat.add_error(
                "음성 출력 비활성화됨. JARVIS_VOICE__TUI_ENABLED=true 로 활성화하세요."
            )
            return
        if not vc.can_speak:
            self._chat.add_error(
                "음성 출력에는 서버 TTS 프로바이더가 필요합니다 "
                "(JARVIS_VOICE__TTS_PROVIDER=supertonic)."
            )
            return
        self.speak_mode = not self.speak_mode
        self._status.set_status(f"음성 출력 {'ON' if self.speak_mode else 'OFF'}")

    def action_voice_input(self) -> None:
        """Ctrl+R: 마이크로 녹음 → 전사 → 입력창에 채운다 (자동 전송하지 않음)."""
        vc = self._voice_controller
        if self._chat is None:
            return
        if vc is None:
            self._chat.add_error(
                "음성 입력 비활성화됨. JARVIS_VOICE__TUI_ENABLED=true 로 활성화하세요."
            )
            return
        if not vc.can_listen:
            self._chat.add_error(
                "음성 입력에는 서버 STT 프로바이더가 필요합니다 "
                "(JARVIS_VOICE__STT_PROVIDER=whisper)."
            )
            return
        self.run_worker(self._voice_input())

    async def _voice_input(self) -> None:
        vc = self._voice_controller
        if vc is None or self._status is None or self._input is None or self._chat is None:
            return
        seconds = self._ctx.settings.voice.tui_record_seconds
        self._status.set_status(f"🎤 듣는 중… ({seconds:g}s)")
        try:
            text = await vc.listen(seconds)
        except Exception as exc:
            self._chat.add_error(f"음성 입력 실패: {exc}")
            self._status.set_status("Ready")
            return
        self._status.set_status("Ready")
        if text.strip():
            self._input.value = text
            self._input.action_end()
            self._input.focus()
        else:
            self._chat.add_tool("음성을 인식하지 못했습니다.")

    def action_proactive_accept(self) -> None:
        self._proactive_feedback(True)

    def action_proactive_dismiss(self) -> None:
        self._proactive_feedback(False)

    def _proactive_feedback(self, accepted: bool) -> None:
        """최근 proactive 발화에 대한 수락/무시를 학습기에 기록 (C3)."""
        if self._last_proactive_id is None or self._chat is None:
            return
        self._last_proactive_id = None
        self._chat.add_status("피드백: 도움됨" if accepted else "피드백: 무시")
        self.run_worker(self._session.record_feedback(accepted))

    async def _speak(self, text: str) -> None:
        vc = self._voice_controller
        if vc is None:
            return
        try:
            await vc.speak(text, lang=self._ctx.settings.voice.tts_lang)
        except Exception as exc:
            if self._chat is not None:
                self._chat.add_error(f"음성 출력 실패: {exc}")

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

    async def action_fork_session(self) -> None:
        """Ctrl+F: 현재 세션을 포크하여 메시지 이력을 복사한 새 세션을 시작한다."""
        if self._ctx.branch_factory is None:
            return

        assert self._chat is not None
        assert self._status is not None
        assert self._input is not None

        self._status.set_status("Forking session...")
        self._input.disabled = True

        try:
            parent_id = self._session._session_id
            new_session = await self._ctx.branch_factory(parent_id)
            new_session.subscribe(self._on_agent_event)
            self._session = new_session
            self._stream_buffer = ""
            self._active_tools = []
            self.is_streaming = False
            self.active_tool_count = 0

            self._chat.clear()
            self._chat.write(
                f"[bold]Forked from:[/bold] [dim]{parent_id}[/dim]\n"
                f"[bold]New session:[/bold] [dim]{new_session._session_id}[/dim]"
            )
            assert self._sidebar is not None
            await self._sidebar.load_sessions(self._ctx.session_repo)
            self._status.set_status("Ready")
        except Exception as exc:
            self._chat.add_error(f"Failed to fork session: {exc}")
            self._status.set_status("Ready")
        finally:
            self._input.disabled = False
            self._input.focus()


def main() -> None:
    from jarvis.ui.tui.startup import main as startup_main

    startup_main()


if __name__ == "__main__":
    main()
