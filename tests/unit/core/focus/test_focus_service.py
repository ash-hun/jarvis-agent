"""FocusService: 시작, 중복 거절, 턴 훅, 종료, 재시작 복원을 가짜 sub-agent 로 검증한다."""

import json
import pytest
import asyncio
from typing import Any
from pathlib import Path

from jarvis.agent_layer.types import AgentEvent, FocusPanelEvent, FocusStateEvent
from jarvis.core.focus.service import FocusService
from jarvis.core.focus.types import FocusCommand
from jarvis.core.focus.store import FocusStore

ANALYSIS = {
    "purpose": ["발표 자료 완성"],
    "reuse": [],
    "needs": ["청중 정보"],
    "next": ["리허설 요청"],
    "prepare": ["예상 질문"],
    "research": ["투자 발표 구성"],
}


class _Reply:
    def __init__(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class _Agent:
    def __init__(self, role: str, calls: list[tuple[str, str]], replies: dict[str, str]) -> None:
        self._role = role
        self._calls = calls
        self._replies = replies

    async def prompt(self, raw_input: str) -> _Reply:
        self._calls.append((self._role, raw_input))
        return _Reply(self._replies[self._role])


class _Session:
    def __init__(self, session_id: str = "s1") -> None:
        self._sid = session_id
        self.events: list[AgentEvent] = []
        self.hook: Any = None

    @property
    def session_id(self) -> str:
        return self._sid

    @property
    def turn_hook(self) -> Any:
        return self.hook

    def set_turn_hook(self, hook: Any) -> None:
        self.hook = hook

    async def emit(self, event: AgentEvent) -> None:
        self.events.append(event)


def _service(tmp_path: Path, calls: list[tuple[str, str]], made: list[str] | None = None) -> FocusService:
    replies = {
        "analysis": json.dumps(ANALYSIS, ensure_ascii=False),
        "progress": '{"steps": [{"title": "목차", "done": false}, {"title": "본문", "done": false}]}',
        "log": "### 2026-10-17 10:00 진행\n사용자가 목차를 요청했다.",
        "reference": "### 선례\n- 출처: https://example.com\n- 특징: 문제-해결-시장 순서",
    }
    ids = iter(["t1", "t2", "t3"])

    async def make_agent(role: str, session_id: str) -> _Agent:
        if made is not None:
            made.append(session_id)
        return _Agent(role, calls, replies)

    return FocusService(
        store=FocusStore(str(tmp_path)),
        make_agent=make_agent,
        clock=lambda: 1_000.0,
        new_id=lambda: next(ids),
    )


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_start_hooks_session_analyzes_plans_and_returns_task(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    service, session = _service(tmp_path, calls), _Session()

    feedback, follow_up = await service.handle(FocusCommand("start", "투자 발표 자료 만들기"), session)
    await _settle()

    assert follow_up == "투자 발표 자료 만들기"
    assert "시작" in feedback
    assert session.hook is service.run_of("s1")
    roles = {role for role, _ in calls}
    assert roles == {"analysis", "progress", "reference"}
    states = [e.state for e in session.events if isinstance(e, FocusStateEvent)]
    assert states[-1]["active"] is True
    assert [s["title"] for s in states[-1]["steps"]] == ["목차", "본문"]
    addendum = session.hook.system_addendum()
    assert "투자 발표 자료 만들기" in addendum and "발표 자료 완성" in addendum


async def test_first_turn_is_not_analyzed_twice(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    service, session = _service(tmp_path, calls), _Session()
    await service.handle(FocusCommand("start", "작업 A"), session)
    await session.hook.before_turn("작업 A")
    assert [r for r, _ in calls].count("analysis") == 1
    await session.hook.before_turn("목차를 짜 줘")
    assert [r for r, _ in calls].count("analysis") == 2


async def test_second_start_is_rejected_and_keeps_first(tmp_path: Path) -> None:
    service, session = _service(tmp_path, []), _Session()
    await service.handle(FocusCommand("start", "작업 A"), session)
    feedback, follow_up = await service.handle(FocusCommand("start", "작업 B"), session)
    assert follow_up is None
    assert "작업 A" in feedback
    assert service.run_of("s1").state.task == "작업 A"


async def test_after_turn_writes_log_and_updates_panels(tmp_path: Path) -> None:
    service, session = _service(tmp_path, []), _Session()
    await service.handle(FocusCommand("start", "작업 A"), session)
    await session.hook.after_turn("목차를 짜 줘", "목차: 1. 문제 2. 해결")
    log = service.store.read_log("t1")
    assert "Focus 시작" in log and "사용자가 목차를 요청했다." in log
    panels = {e.area: e for e in session.events if isinstance(e, FocusPanelEvent)}
    assert set(panels) == {"analysis", "log", "reference"}
    assert panels["log"].busy is False


async def test_stop_releases_and_is_idempotent(tmp_path: Path) -> None:
    service, session = _service(tmp_path, []), _Session()
    await service.handle(FocusCommand("start", "작업 A"), session)
    first, _ = await service.handle(FocusCommand("stop"), session)
    second, _ = await service.handle(FocusCommand("stop"), session)
    assert "마칩니다" in first and "없습니다" in second
    assert session.hook is None
    assert service.store.active_task("s1") is None
    assert "Focus 종료" in service.store.read_log("t1")
    assert session.events[-1] == FocusStateEvent(session_id="s1", state={"active": False, "task_id": "t1"})
    _, follow_up = await service.handle(FocusCommand("start", "작업 B"), session)
    assert follow_up == "작업 B"


async def test_restore_after_restart_rehooks_once(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    first = _service(tmp_path, calls)
    await first.handle(FocusCommand("start", "작업 A"), _Session())

    restarted, session = _service(tmp_path, calls), _Session()
    run = await restarted.restore(session)
    again = await restarted.restore(session)
    assert run is not None and again is run and session.hook is run
    assert run.state.task == "작업 A"
    events = run.panel_events()
    assert isinstance(events[0], FocusStateEvent) and events[0].state["task"] == "작업 A"
    assert {e.area for e in events[1:] if isinstance(e, FocusPanelEvent)} == {"reference", "log", "analysis"}


async def test_orphan_active_marker_is_cleared(tmp_path: Path) -> None:
    service, session = _service(tmp_path, []), _Session()
    service.store.claim("s1", "ghost")
    assert await service.restore(session) is None
    assert service.store.active_task("s1") is None


async def test_failing_sub_agent_does_not_break_turn(tmp_path: Path) -> None:
    service, session = _service(tmp_path, []), _Session()
    await service.handle(FocusCommand("start", "작업 A"), session)

    class _Broken:
        async def prompt(self, raw_input: str) -> Any:
            raise RuntimeError("model down")

    run = service.run_of("s1")
    run._agents["log"] = _Broken()
    await session.hook.after_turn("지시", "응답")
    assert "Focus 시작" in service.store.read_log("t1")


async def test_sub_agents_are_made_once_per_role(tmp_path: Path) -> None:
    made: list[str] = []
    service, session = _service(tmp_path, [], made), _Session()
    await service.handle(FocusCommand("start", "작업 A"), session)
    await session.hook.after_turn("지시 1", "응답 1")
    await session.hook.after_turn("지시 2", "응답 2")
    await _settle()
    assert sorted(made) == sorted({f"focus_t1_{r}" for r in ("analysis", "progress", "reference", "log")})


@pytest.mark.parametrize("action", ["status"])
async def test_status_without_task(tmp_path: Path, action: str) -> None:
    service = _service(tmp_path, [])
    feedback, follow_up = await service.handle(FocusCommand(action), _Session())
    assert "없습니다" in feedback and follow_up is None
