"""[ui] SlashPicker: TUI 입력창 위에 뜨는 슬래시 명령 자동완성 팝업."""

from __future__ import annotations

from textual.widgets import OptionList
from textual.widgets.option_list import Option


class SlashPicker(OptionList):
    """
    슬래시 명령 자동완성 팝업.

    '/'를 입력할 때 Input 바로 위에 마운트되어 방향키로 탐색,
    Enter/Space로 선택, Escape로 닫을 수 있다.
    """

    DEFAULT_CSS = """
    SlashPicker {
        height: auto;
        max-height: 8;
        border: solid $accent;
        margin: 0 1 0 1;
        background: $surface;
    }
    """

    def populate(self, commands: dict[str, str], query: str = "") -> None:
        """
        등록된 명령 dict를 받아 query로 필터링 후 목록을 갱신한다.
        query가 빈 문자열이면 전체를 표시한다.
        """
        self.clear_options()
        q = query.lower()
        for name, desc in sorted(commands.items()):
            if q and not name.startswith(q):
                continue
            label = f"/{name:<14}  {desc}" if desc else f"/{name}"
            self.add_option(Option(label, id=name))
