"""[core] 에이전트별 작업 지표와 백엔드 프로세스 지표를 한 장으로 모은다. Ion 가 밖에서 읽는다."""

import os
import time
import asyncio
from typing import Any
from dataclasses import asdict, dataclass
from collections.abc import Callable, Iterable

from jarvis.core.platform.loop_lag import LoopLag, LoopLagMonitor
from jarvis.core.workflow.workflow_types import JobRecord

# 스케줄 작업은 에이전트가 있지만 성찰, 기억 정리, 외부 조회는 프로세스 전체의 일이라 이 묶음으로 센다
SHARED = "shared"
SCHEDULE_PREFIX = "schedule:"

AgentOfJob = Callable[[str], str | None]
# 열린 세션 id → 에이전트 id
SessionAgents = Callable[[], dict[str, str]]


@dataclass(frozen=True)
class AgentMetrics:
    """에이전트 하나의 작업 상태. fail_streak 는 그 에이전트 작업 중 가장 긴 연속 실패다."""

    agent: str
    jobs: int
    running: int
    fail_streak: int
    last_ok_ms: int | None
    last_error: str
    open_sessions: int


@dataclass(frozen=True)
class ProcessMetrics:
    """백엔드 프로세스 하나의 자원. htop 의 한 줄에 해당한다."""

    pid: int
    rss_bytes: int
    cpu_percent: float
    threads: int
    open_fds: int | None
    asyncio_tasks: int
    uptime_sec: float


def agent_metrics(
    records: Iterable[JobRecord], agent_of: AgentOfJob, agents: Iterable[str], sessions: dict[str, str]
) -> list[AgentMetrics]:
    """작업 기록을 에이전트별로 접는다. 작업이 없는 에이전트도 0 으로 나온다. 순수 함수."""
    buckets: dict[str, list[JobRecord]] = {a: [] for a in agents}
    buckets.setdefault(SHARED, [])
    for record in records:
        buckets.setdefault(agent_of(record.job_id) or SHARED, []).append(record)
    opened: dict[str, int] = {}
    for agent in sessions.values():
        opened[agent] = opened.get(agent, 0) + 1
    out = []
    for agent in sorted(buckets):
        jobs = buckets[agent]
        oks = [r.last_ended_ms for r in jobs if r.last_ok and r.last_ended_ms is not None]
        failed = [r for r in jobs if r.last_ok is False]
        out.append(AgentMetrics(
            agent=agent,
            jobs=len(jobs),
            running=sum(1 for r in jobs if r.running),
            fail_streak=max((r.fail_streak for r in jobs), default=0),
            last_ok_ms=max(oks) if oks else None,
            last_error=max(failed, key=lambda r: r.last_ended_ms or 0).last_error if failed else "",
            open_sessions=opened.get(agent, 0),
        ))
    return out


def schedule_agent_of(task_agents: dict[str, str]) -> AgentOfJob:
    """`schedule:<작업 이름>` 작업을 그 작업의 에이전트로 잇는 함수. 그 밖의 작업은 None(shared)."""

    def agent_of(job_id: str) -> str | None:
        if not job_id.startswith(SCHEDULE_PREFIX):
            return None
        return task_agents.get(job_id[len(SCHEDULE_PREFIX):])

    return agent_of


class PlatformMetricsService:
    """지표 한 장을 만든다. 프로세스 지표는 psutil 로 지금 프로세스를 읽는다."""

    def __init__(
        self,
        records: Callable[[], list[JobRecord]],
        agent_of: AgentOfJob,
        agents: Callable[[], list[str]],
        sessions: SessionAgents,
        loop_lag: LoopLagMonitor | None = None,
        pid: int | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._records = records
        self._agent_of = agent_of
        self._agents = agents
        self._sessions = sessions
        self._loop_lag = loop_lag
        self._now = now
        import psutil

        self._process = psutil.Process(pid if pid is not None else os.getpid())
        # 첫 cpu_percent 는 기준점이 없어 0 이다. 여기서 한 번 재 두면 다음 호출부터 구간 평균이 나온다
        self._process.cpu_percent(interval=None)

    def process(self) -> ProcessMetrics:
        with self._process.oneshot():
            mem = self._process.memory_info()
            try:
                fds: int | None = self._process.num_fds()
            except (AttributeError, OSError):  # Windows 와 권한 없는 환경
                fds = None
            return ProcessMetrics(
                pid=self._process.pid,
                rss_bytes=mem.rss,
                cpu_percent=self._process.cpu_percent(interval=None),
                threads=self._process.num_threads(),
                open_fds=fds,
                asyncio_tasks=_task_count(),
                uptime_sec=max(0.0, self._now() - self._process.create_time()),
            )

    def snapshot(self) -> dict[str, Any]:
        """`GET /api/platform/metrics` 본문. 같은 상태면 같은 값(시각 제외)."""
        lag: LoopLag = self._loop_lag.snapshot() if self._loop_lag is not None else LoopLag(0.0, 0.0, 0)
        agents = agent_metrics(self._records(), self._agent_of, self._agents(), self._sessions())
        return {
            "at_ms": int(self._now() * 1000),
            "process": asdict(self.process()),
            "loop_lag": asdict(lag),
            "agents": [asdict(m) for m in agents],
        }


def _task_count() -> int:
    try:
        return len(asyncio.all_tasks())
    except RuntimeError:  # 루프 밖에서 부르면 0
        return 0
