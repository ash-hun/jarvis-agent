"""tui 의 SidebarPane: 세션 목록에서 분기 세션만 ↳ 로 들여 보이는지 검증한다."""

from textual.app import App, ComposeResult
from textual.widgets import Label, ListView

from jarvis.ui.tui.components.sidebar import SidebarPane
from jarvis.model_layer.model_types import UserMessage


class _SidebarApp(App[None]):
    def compose(self) -> ComposeResult:
        yield SidebarPane()


async def test_load_sessions_marks_only_branches_with_arrow(jsonl_repo):
    await jsonl_repo.create(session_id="root-abc123456789")
    await jsonl_repo.append("root-abc123456789", UserMessage(content="hi"))
    branch = await jsonl_repo.create_branch("root-abc123456789")
    app = _SidebarApp()

    async with app.run_test() as pilot:
        await app.query_one(SidebarPane).load_sessions(jsonl_repo)
        await pilot.pause()
        labels = [str(label.render()) for label in app.query_one("#session-list", ListView).query(Label)]

    assert labels == ["root-abc123456 (1)", f"↳ {branch.session_id[:12]} (1)"]
