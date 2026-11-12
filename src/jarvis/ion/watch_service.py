"""[ion] 감시 루프. 관측을 규칙에 넣어 사고를 열고 한 번 알리고, 답에 따라 행동하고, 신호가 사라지면 닫는다."""

import json
import time
import asyncio
import contextlib
from typing import Any
from collections import deque
from datetime import datetime
from dataclasses import asdict
from collections.abc import Awaitable, Callable

from jarvis.ion.health_rules import AgentObservation, Observation, Signal, Thresholds, evaluate, incident_id
from jarvis.ion.docker_client import ContainerState, DockerClient
from jarvis.ion.incident_store import Incident, IncidentStore
from jarvis.ion.backend_client import BackendClient
from jarvis.common.logger import get_logger
from jarvis.ion.ion_config import IonConfig

# 사고 알림 payload 를 받는 곳(푸시, SSE). 실패해도 루프는 계속된다
Notify = Callable[[dict[str, Any]], Awaitable[None]]
# 주기적으로 같이 돌릴 일(구독 복사). 실패해도 루프는 계속된다
Chore = Callable[[], Awaitable[None]]
ACTIONS = ("restart", "stop", "pause", "ignore")
# 신호별로 사용자에게 보일 버튼. 첫 번째가 추천이다
CHOICES: dict[str, tuple[str, ...]] = {
    "backend_down": ("restart", "ignore"),
    "restart_loop": ("stop", "ignore"),
    "loop_stall": ("restart", "ignore"),
    "memory_high": ("restart", "ignore"),
    "agent_failing": ("pause", "ignore"),
    "schedule_stale": ("restart", "ignore"),
}
TITLES = {
    "backend_down": "백엔드가 응답하지 않아요",
    "restart_loop": "백엔드가 재시작을 반복해요",
    "loop_stall": "백엔드가 멈춘 것 같아요",
    "memory_high": "백엔드 메모리가 거의 찼어요",
    "agent_failing": "{target} 의 작업이 계속 실패해요",
    "schedule_stale": "{target} 의 차례가 오래 멈춰 있어요",
}
logger = get_logger(__name__)


def to_observation(
    at_ms: int, health_ok: bool | None, metrics: dict[str, Any] | None, container: ContainerState | None
) -> Observation:
    """클라이언트가 가져온 것을 규칙 입력으로. 못 가져온 것은 None 으로 남는다. 순수 함수."""
    agents: dict[str, AgentObservation] = {}
    lag: float | None = None
    if metrics is not None:
        lag = float((metrics.get("loop_lag") or {}).get("max_ms") or 0.0)
        for row in metrics.get("agents") or []:
            if row.get("agent") == "shared":
                continue
            agents[str(row["agent"])] = AgentObservation(
                fail_streak=int(row.get("fail_streak") or 0),
                last_ok_ms=row.get("last_ok_ms"),
                scheduled=int(row.get("jobs") or 0) > 0,
            )
    return Observation(
        at_ms=at_ms,
        health_ok=health_ok,
        restart_count=container.restart_count if container is not None else None,
        loop_lag_ms=lag,
        rss_bytes=container.memory_usage if container is not None else None,
        memory_limit_bytes=container.memory_limit if container is not None else None,
        agents=agents,
    )


def notification(incident: Incident, hud_url: str) -> dict[str, Any]:
    """푸시와 SSE 가 같이 쓰는 사고 알림. tag 가 사고 id 라 같은 사고는 한 알림으로 겹친다. 순수 함수."""
    title = TITLES.get(incident.kind, incident.kind).format(target=incident.target)
    return {
        "type": "incident",
        "id": incident.id,
        "kind": incident.kind,
        "target": incident.target,
        "title": f"Ion: {title}",
        "body": incident.detail,
        "tag": incident.id,
        "url": hud_url,
        "actions": list(CHOICES.get(incident.kind, ("ignore",))),
    }


class WatchService:
    """한 바퀴(tick)는 관측, 판정, 사고 갱신, 알림 순이다. 같은 상태로 두 번 돌아도 알림은 한 번이다."""

    def __init__(
        self,
        cfg: IonConfig,
        backend: BackendClient,
        docker: DockerClient,
        store: IncidentStore,
        notify: Notify,
        chores: list[Chore] | None = None,
        now_ms: Callable[[], int] = lambda: int(time.time() * 1000),
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._cfg = cfg
        self._rules: Thresholds = cfg.thresholds.rules()
        self._backend = backend
        self._docker = docker
        self._store = store
        self._notify = notify
        self._chores = chores or []
        self._now_ms = now_ms
        self._clock = clock
        self._history: deque[Observation] = deque(maxlen=cfg.history)
        self._container: ContainerState | None = None
        self._metrics: dict[str, Any] | None = None
        self._ticks = 0
        self._task: asyncio.Task[None] | None = None

    @property
    def store(self) -> IncidentStore:
        return self._store

    async def tick(self) -> list[Signal]:
        """한 바퀴. 돌려주는 값은 지금 켜진 신호다."""
        self._ticks += 1
        heavy = self._ticks % self._cfg.metrics_every == 1 or self._cfg.metrics_every <= 1
        health = await self._backend.health()
        if heavy:
            self._metrics = await self._backend.metrics() if health else None
            found = await self._docker.find(self._cfg.backend_service)
            self._container = await self._docker.with_stats(found) if found is not None else None
            for chore in self._chores:
                try:
                    await chore()
                except Exception as exc:
                    logger.info(f"[Ion] chore failed: {exc!r}")
        at = self._now_ms()
        self._history.append(to_observation(at, health, self._metrics, self._container))
        signals = evaluate(list(self._history), self._rules, self._clock())
        await self._reconcile(signals, at)
        return signals

    async def _reconcile(self, signals: list[Signal], at_ms: int) -> None:
        """켜진 신호마다 사고 하나를 열고, 아직 안 알린 사고를 알리고, 신호가 사라진 사고를 닫는다."""
        live = {(s.kind, s.target) for s in signals}
        opened = {(i.kind, i.target): i for i in self._store.open_incidents()}
        for signal in signals:
            incident = opened.get((signal.kind, signal.target))
            if incident is None:
                incident, _ = self._store.open(
                    Incident(incident_id(signal, at_ms), signal.kind, signal.target, signal.detail, at_ms)
                )
            if incident.notified_ms is None:
                try:
                    await self._notify(notification(incident, self._cfg.hud_url))
                except Exception as exc:
                    logger.info(f"[Ion] notify failed, will retry next tick: {exc!r}")
                    continue
                self._store.mark_notified(incident.id, at_ms)
                logger.info(f"[Ion] incident opened and notified: {incident.id}")
        for key, incident in opened.items():
            if key not in live:
                self._store.close(incident.id, at_ms)
                logger.info(f"[Ion] incident closed: {incident.id}")

    async def respond(self, incident_id_: str, action: str) -> Incident | None:
        """사용자의 답. 모르는 사고면 None. 행동은 답을 처음 받을 때만 한다(같은 답을 두 번 눌러도 한 번)."""
        incident = self._store.get(incident_id_)
        if incident is None or action not in ACTIONS:
            return None
        if incident.response is not None:
            return incident
        result = await self._act(incident, action)
        logger.info(f"[Ion] incident {incident.id} response={action} result={result}")
        return self._store.respond(incident.id, action, self._now_ms(), result)

    async def _act(self, incident: Incident, action: str) -> str:
        service = self._cfg.backend_service
        if action == "restart":
            return "재기동함" if await self._docker.restart(service) else "재기동 실패"
        if action == "stop":
            return "멈춤" if await self._docker.stop(service) else "멈추기 실패"
        if action == "pause":
            names = [
                str(j["name"]) for j in await self._backend.jobs()
                if j.get("agent") == incident.target and j.get("enabled") and j.get("name")
            ]
            done = [n for n in names if await self._backend.set_task_enabled(n, False)]
            return f"작업 {len(done)}개 멈춤" if names else "멈출 작업 없음"
        return "무시"

    def status(self) -> dict[str, Any]:
        """`GET /ion/status` 본문."""
        latest = self._history[-1] if self._history else None
        return {
            "at_ms": self._now_ms(),
            "backend_ok": latest.health_ok if latest is not None else None,
            "observed_ms": latest.at_ms if latest is not None else None,
            "container": asdict(self._container) if self._container is not None else None,
            "loop_lag_ms": latest.loop_lag_ms if latest is not None else None,
            "agents": {k: asdict(v) for k, v in (latest.agents.items() if latest is not None else [])},
            "incidents": [asdict(i) for i in self._store.open_incidents()],
        }

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:  # 한 바퀴의 오류가 감시를 끝내지 않게
                logger.warning(f"[Ion] tick failed: {exc!r}")
            await asyncio.sleep(self._cfg.poll_sec)


def sse_line(payload: dict[str, Any]) -> str:
    """SSE 한 건. 순수 함수."""
    return f"event: {payload.get('type', 'message')}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
