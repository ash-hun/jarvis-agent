"""run_focus: 안내 메시지의 agent_end 가 메인 에이전트가 이어 도는지 알려, 화면이 음성 요청 표시를 지키게 한다."""

import pytest
from typing import Any

from jarvis.core.focus.focus_types import parse_command
from jarvis.ui.web.ws_tasks import run_focus


class FakeAdapter:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    async def show_error(self, message: str) -> None:
        self.sent.append({"type": "error", "message": message})


class FakeSession:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def prompt(self, text: str, credentials: dict[str, str]) -> None:
        self.prompts.append(text)


class FakeFocus:
    def __init__(self, follow_up: str | None) -> None:
        self._follow_up = follow_up

    async def handle(self, command: Any, session: Any) -> tuple[str, str | None]:
        return "[Focus] 안내", self._follow_up


@pytest.mark.parametrize(
    ("follow_up", "continues", "prompts"), [("회의 아젠다", True, ["회의 아젠다"]), (None, False, [])]
)
async def test_agent_end_says_whether_main_agent_continues(follow_up, continues, prompts):
    adapter, session = FakeAdapter(), FakeSession()
    command = parse_command("/focus 회의 아젠다")
    assert command is not None

    await run_focus(session, adapter, FakeFocus(follow_up), command, {})  # type: ignore[arg-type]

    assert adapter.sent == [
        {"type": "agent_start"},
        {"type": "stream_delta", "text": "[Focus] 안내"},
        {"type": "agent_end", "continues": continues},
    ]
    assert session.prompts == prompts
