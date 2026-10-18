"""[ui] TUI 렌더링이 쓰는 불변 상태 값(활성 도구, 메모리 통계, UIState)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActiveTool:
    tool_call_id: str
    tool_name: str
    started_at: int


@dataclass(frozen=True)
class MemoryStats:
    message_count: int
    backend: str


@dataclass(frozen=True)
class UIState:
    """
    TUI 렌더링에 필요한 모든 파생 상태.

    frozen=True: 변경 불가 — 상태 변경 시 새 인스턴스로 교체.
    Warp: ViewState / Hunk: buildReviewState 패턴.
    """

    session_id: str | None
    is_streaming: bool
    active_tools: tuple[ActiveTool, ...]
    stream_buffer: str
    sidebar_visible: bool
    status_text: str
    error_text: str | None
    memory_stats: MemoryStats | None = None


def build_ui_state(
    session_id: str | None = None,
    is_streaming: bool = False,
    active_tools: list[ActiveTool] | None = None,
    stream_buffer: str = "",
    sidebar_visible: bool = True,
    status_text: str = "Ready",
    error_text: str | None = None,
    memory_stats: MemoryStats | None = None,
) -> UIState:
    """
    UIState 순수 파생 함수. 부작용 없음 — Textual 없이 단위 테스트 가능.
    Hunk: buildReviewState() 패턴.
    """
    tools = active_tools or []

    if is_streaming:
        computed_status = "Streaming..."
    elif tools:
        computed_status = f"{len(tools)} tool(s) running"
    else:
        computed_status = status_text

    return UIState(
        session_id=session_id,
        is_streaming=is_streaming,
        active_tools=tuple(tools),
        stream_buffer=stream_buffer,
        sidebar_visible=sidebar_visible,
        status_text=computed_status,
        error_text=error_text,
        memory_stats=memory_stats,
    )
