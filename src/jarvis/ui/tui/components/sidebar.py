from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, ListItem, ListView

if TYPE_CHECKING:
    from jarvis.agent_layer.session.jsonl import JsonlSessionRepo
    from jarvis.core.tools.registry import ToolRegistry


class SidebarPane(Vertical):
    """
    사이드바 패널 — 세션 목록 + 도구 목록.
    Hunk: SidebarPane 패턴.
    """

    DEFAULT_CSS = """
    SidebarPane {
        width: 26;
        border-right: solid $primary-darken-2;
        padding: 0;
    }
    SidebarPane Label.section-title {
        color: $text-muted;
        padding: 1 1 0 1;
        text-style: bold;
    }
    SidebarPane ListView {
        height: auto;
        max-height: 12;
        background: transparent;
    }
    SidebarPane ListItem {
        padding: 0 1;
    }
    """

    async def load_sessions(self, session_repo: JsonlSessionRepo) -> None:
        """세션 레포에서 최근 세션 목록을 로드하여 사이드바에 표시."""
        sessions = await session_repo.list()
        session_list = self.query_one("#session-list", ListView)
        await session_list.clear()
        for meta in sessions[:10]:
            short_id = meta.session_id[:14]
            label = f"{short_id} ({meta.message_count})"
            session_list.append(ListItem(Label(label)))

    def load_tools(self, tool_registry: ToolRegistry) -> None:
        """도구 레지스트리에서 등록된 도구 목록을 표시."""
        tool_list = self.query_one("#tool-list", ListView)
        for tool in tool_registry.list_all():
            tool_list.append(ListItem(Label(f"⚙ {tool.name}")))

    def compose(self) -> ComposeResult:
        yield Label("Sessions", classes="section-title")
        yield ListView(id="session-list")
        yield Label("Tools", classes="section-title")
        yield ListView(id="tool-list")
