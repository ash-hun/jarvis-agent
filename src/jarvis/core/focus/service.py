"""[core] FocusService: 세션마다 Focus 작업 하나를 열고 닫으며, 턴마다 sub-agent 넷을 돌려 화면에 밀어 보낸다."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime
from typing import Any, Protocol

from jarvis.agent_layer.types import AgentEvent, FocusPanelEvent, FocusStateEvent
from jarvis.common.logger import get_logger
from jarvis.core.focus.prompts import (
    analysis_request,
    log_request,
    main_addendum,
    progress_request,
    reference_request,
)
from jarvis.core.focus.store import FocusStore
from jarvis.core.focus.types import (
    FocusCommand,
    FocusState,
    apply_plan,
    eta_sec,
    extract_json,
    progress,
    render_analysis,
    state_payload,
    with_instruction,
)

PANEL_TAIL_CHARS = 8000
READY_TIMEOUT_SEC = 30.0
FIRST_REPLY = "(아직 응답 없음. 작업을 막 시작했다)"

logger = get_logger(__name__)


class SubAgent(Protocol):
    async def prompt(self, raw_input: str) -> Any: ...


class FocusSession(Protocol):
    """FocusService 가 메인 세션에서 쓰는 것만. AgentSession 이 만족한다."""

    @property
    def session_id(self) -> str: ...

    @property
    def turn_hook(self) -> Any: ...

    def set_turn_hook(self, hook: Any) -> None: ...

    async def emit(self, event: AgentEvent) -> None: ...


AgentMaker = Callable[[str, str], Awaitable[SubAgent]]


def _reply_text(message: Any) -> str:
    text = getattr(message, "text", "") if message else ""
    return str(text() if callable(text) else text or "")


class FocusRun:
    """활성 Focus 작업 하나. 메인 세션의 턴 훅이 되어 턴 앞에서 분석을, 뒤에서 기록과 진행을 돌린다."""

    def __init__(self, service: "FocusService", session: FocusSession, state: FocusState) -> None:
        self._service = service
        self._session = session
        self.state = state
        self._agents: dict[str, SubAgent] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        # start 가 첫 지시를 미리 분석했으면 그 턴의 before_turn 은 다시 분석하지 않는다
        self._pre_analyzed: str | None = None

    # ── TurnHook ──────────────────────────────────────────────────────────────
    def system_addendum(self) -> str | None:
        store = self._service.store
        task_id = self.state.task_id
        return main_addendum(self.state, store.last_analysis(task_id), store.read_references(task_id))

    async def before_turn(self, user_input: str) -> None:
        if user_input == self._pre_analyzed:
            self._pre_analyzed = None
            return
        await self.analyze(user_input)

    async def after_turn(self, user_input: str, reply: str) -> None:
        await asyncio.gather(self.write_log(user_input, reply), self.track(user_input, reply))

    # ── sub-agent 일 ──────────────────────────────────────────────────────────
    async def analyze(self, instruction: str) -> None:
        request = analysis_request(self.state, instruction)
        self.state = with_instruction(self.state, instruction)
        self._service.store.save_state(self.state)
        await self._panel("analysis", busy=True)
        raw = await self._ask("analysis", request)
        analysis = extract_json(raw) if raw else None
        if analysis is not None:
            self._service.store.append_analysis(self.state.task_id, analysis)
            queries = [str(q) for q in analysis.get("research") or [] if str(q).strip()]
            if queries:
                self._service.spawn(self.research(queries[0]))
        await self._panel("analysis")

    async def research(self, query: str) -> None:
        # 조사가 이미 돌고 있으면 _ask 의 역할 잠금에서 차례를 기다린다
        await self._panel("reference", busy=True)
        found = await self._ask("reference", reference_request(self.state.task, query))
        if found.strip():
            self._service.store.append_reference(self.state.task_id, f"## 조사: {query}\n\n{found}")
        await self._panel("reference")

    async def write_log(self, instruction: str, reply: str) -> None:
        await self._panel("log", busy=True)
        entry = await self._ask("log", log_request(self._service.timestamp(), instruction, reply))
        if entry.strip():
            self._service.store.append_log(self.state.task_id, entry)
        await self._panel("log")

    async def track(self, instruction: str, reply: str) -> None:
        raw = await self._ask("progress", progress_request(self.state, instruction, reply))
        plan = extract_json(raw) if raw else None
        steps = plan.get("steps") if plan else None
        if isinstance(steps, list):
            self.state = replace(self.state, steps=apply_plan(self.state.steps, steps, self._service.now()))
            self._service.store.save_state(self.state)
        await self.push_state()

    # ── 화면 ──────────────────────────────────────────────────────────────────
    async def push_state(self) -> None:
        payload = state_payload(self.state, self._service.now())
        await self._session.emit(FocusStateEvent(session_id=self.state.session_id, state=payload))

    async def _panel(self, area: str, busy: bool = False) -> None:
        markdown = self._service.panel_markdown(self.state.task_id, area)
        await self._session.emit(
            FocusPanelEvent(session_id=self.state.session_id, area=area, markdown=markdown, busy=busy)
        )

    def panel_events(self) -> list[AgentEvent]:
        payload = state_payload(self.state, self._service.now())
        events: list[AgentEvent] = [FocusStateEvent(session_id=self.state.session_id, state=payload)]
        for area in ("reference", "log", "analysis"):
            markdown = self._service.panel_markdown(self.state.task_id, area)
            events.append(FocusPanelEvent(session_id=self.state.session_id, area=area, markdown=markdown))
        return events

    def _lock(self, role: str) -> asyncio.Lock:
        return self._locks.setdefault(role, asyncio.Lock())

    async def _ask(self, role: str, request: str) -> str:
        """역할 sub-agent 에게 묻는다. 같은 역할은 한 번에 하나씩(세션이 동시 prompt 를 거부한다). 실패하면 ""."""
        async with self._lock(role):
            try:
                agent = self._agents.get(role)
                if agent is None:
                    agent = await self._service.make_agent(role, f"focus_{self.state.task_id}_{role}")
                    self._agents[role] = agent
                return _reply_text(await agent.prompt(request))
            except Exception as exc:
                logger.info(f"[Focus] {role} sub-agent failed: {exc!r}")
                return ""


class FocusService:
    """세션 id → 활성 FocusRun. 활성 표시의 정본은 store 의 active 파일이라 재시작 뒤 restore 로 되살린다."""

    def __init__(
        self,
        store: FocusStore,
        make_agent: AgentMaker,
        clock: Callable[[], float],
        new_id: Callable[[], str],
        ready_timeout_sec: float = READY_TIMEOUT_SEC,
    ) -> None:
        self.store = store
        self.make_agent = make_agent
        self.now = clock
        self._new_id = new_id
        self._ready_timeout = ready_timeout_sec
        self._runs: dict[str, FocusRun] = {}
        self._tasks: set[asyncio.Task[Any]] = set()

    def timestamp(self) -> str:
        return datetime.fromtimestamp(self.now()).strftime("%Y-%m-%d %H:%M")

    def run_of(self, session_id: str) -> FocusRun | None:
        return self._runs.get(session_id)

    async def handle(self, command: FocusCommand, session: FocusSession) -> tuple[str, str | None]:
        """(사용자에게 보일 안내, 이어서 메인 에이전트에 보낼 지시) 를 돌려준다."""
        if command.action == "start":
            return await self.start(session, command.task)
        if command.action == "stop":
            return await self.stop(session), None
        return self.status(session.session_id), None

    async def start(self, session: FocusSession, task: str) -> tuple[str, str | None]:
        sid = session.session_id
        current = self._runs.get(sid) or await self.restore(session)
        if current is not None:
            return f"[Focus] 이미 진행 중인 작업이 있습니다: {current.state.task}\n끝내려면 /focus stop", None
        task_id = self._new_id()
        if not self.store.claim(sid, task_id):
            return "[Focus] 이 세션에 이미 Focus 작업이 있습니다. /focus 로 현황을 확인하세요.", None
        state = FocusState(task_id=task_id, session_id=sid, task=task, started_at=self.now())
        self.store.save_state(state)
        opening = f"### {self.timestamp()} Focus 시작\n사용자가 Focus 모드로 작업을 지시했다. 작업: {task}"
        self.store.append_log(task_id, opening)
        run = FocusRun(self, session, state)
        self._runs[sid] = run
        session.set_turn_hook(run)
        for event in run.panel_events():
            await session.emit(event)
        # 첫 응답이 분석과 단계 계획을 보고 시작하게 기다린다. 조사는 오래 걸리니 뒤에서
        run._pre_analyzed = task
        self.spawn(run.research(task))
        try:
            await asyncio.wait_for(
                asyncio.gather(run.analyze(task), run.track(task, FIRST_REPLY)), timeout=self._ready_timeout
            )
        except TimeoutError:
            logger.info(f"[Focus] start analysis late (>{self._ready_timeout}s): main turn starts without it")
        return f"[Focus] 작업을 시작합니다: {task}", task

    async def stop(self, session: FocusSession) -> str:
        sid = session.session_id
        run = self._runs.pop(sid, None) or await self._load(session)
        self._runs.pop(sid, None)
        if run is None:
            return "[Focus] 진행 중인 Focus 작업이 없습니다."
        if session.turn_hook is run:
            session.set_turn_hook(None)
        percent = round(progress(run.state.steps) * 100)
        closing = f"### {self.timestamp()} Focus 종료\n사용자가 Focus 모드를 종료했다. 진행률은 {percent}% 였다."
        self.store.append_log(run.state.task_id, closing)
        self.store.release(sid)
        await session.emit(FocusStateEvent(session_id=sid, state={"active": False, "task_id": run.state.task_id}))
        return f"[Focus] 작업을 마칩니다 ({percent}%). 기록: {self.store.log_path(run.state.task_id)}"

    def status(self, session_id: str) -> str:
        run = self._runs.get(session_id)
        if run is None:
            return "[Focus] 진행 중인 작업이 없습니다. 시작: /focus <작업>"
        s = run.state
        eta = eta_sec(s, self.now())
        lines = [f"[Focus] {s.task}", f"진행 {round(progress(s.steps) * 100)}%"]
        lines += [f"  [{'x' if step.done else ' '}] {step.title}" for step in s.steps]
        if eta is not None:
            lines.append(f"예상 남은 시간 {round(eta / 60)}분")
        return "\n".join(lines)

    async def restore(self, session: FocusSession) -> FocusRun | None:
        """store 에 활성 작업이 있는데 메모리에 없으면(재시작) 되살려 턴 훅을 다시 끼운다. 두 번 불러도 하나다."""
        sid = session.session_id
        if sid in self._runs:
            return self._runs[sid]
        run = await self._load(session)
        if run is not None:
            self._runs[sid] = run
            session.set_turn_hook(run)
        return run

    async def _load(self, session: FocusSession) -> FocusRun | None:
        task_id = self.store.active_task(session.session_id)
        state = self.store.load_state(task_id) if task_id else None
        if state is None:
            if task_id:
                self.store.release(session.session_id)  # 상태 파일이 없는 활성 표시는 고아다
            return None
        return FocusRun(self, session, state)

    def panel_markdown(self, task_id: str, area: str) -> str:
        if area == "reference":
            return self.store.read_references(task_id)[-PANEL_TAIL_CHARS:]
        if area == "log":
            return self.store.read_log(task_id)[-PANEL_TAIL_CHARS:]
        analysis = self.store.last_analysis(task_id)
        return render_analysis(analysis) if analysis else ""

    def spawn(self, coro: Awaitable[None]) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
