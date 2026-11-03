"""[ui] Workflow 화면 REST: 에이전트 관계 그래프(에이전트, sub-agent, 최근 위임)와 백그라운드 작업 현황."""

from typing import Any
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from jarvis.core.workflow.workflow_tracker import SUBAGENT_PREFIX
from jarvis.ui.web.router.tool_router import short_description
from jarvis.core.workflow.workflow_types import JobRecord
from jarvis.ui.web.web_state import WebState

WORKFLOW_EXAMPLE = {
    "agents": [{"id": "main", "name": "J.A.R.V.I.S.", "primary": "#5fc8e2", "main": True}],
    "subagents": ["researcher"],
    "capabilities": [
        {"name": "bash", "description": "셸 명령 실행", "approval": True, "agents": ["main"]},
        {"name": "web_search", "description": "웹 검색", "approval": False, "agents": ["main", "karen"]},
    ],
    "edges": [{"edge_id": "default:call_1", "kind": "ask", "source": "main", "target": "karen",
               "label": "오늘 일정 정리", "started_ms": 1791613276663, "ended_ms": 1791613279001, "ok": True}],
}
JOBS_EXAMPLE = {
    "jobs": [{"job_id": "schedule:morning", "kind": "schedule", "label": "아침 브리핑", "runs": 3, "running": False,
              "last_started_ms": 1791613276663, "last_ended_ms": 1791613281000, "last_ok": True, "last_error": "",
              "enabled": True, "next_run": "2026-11-04T09:00:00+09:00", "agent": "main"}],
    "daemon": {"enabled": True, "trigger": "interval", "interval_sec": 120, "idle_sec": 180},
}


def merge_jobs(records: list[JobRecord], schedules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """스케줄 목록(아직 돈 적 없는 것 포함)에 실행 기록을 얹고, 스케줄이 아닌 작업 기록을 뒤에 붙인다. 순수 함수."""
    by_id = {r.job_id: r for r in records}
    jobs: list[dict[str, Any]] = []
    for sched in schedules:
        job_id = f"schedule:{sched['name']}"
        record = by_id.pop(job_id, None) or JobRecord(
            job_id=job_id, kind="schedule", label=str(sched.get("label") or sched["name"]), runs=0, running=False
        )
        jobs.append({**record.to_dict(), **{k: sched[k] for k in ("enabled", "next_run", "agent")}})
    jobs.extend(r.to_dict() for r in sorted(by_id.values(), key=lambda r: r.job_id))
    return jobs


def capability_map(tools_by_agent: dict[str, list[str]]) -> list[dict[str, Any]]:
    """도구 이름마다 그 도구를 쓰는 에이전트 목록. 한 에이전트만 가진 것이 먼저, 그다음 이름순. 순수 함수.

    에이전트 순서는 tools_by_agent 의 순서를 따른다. sub-agent 위임 도구(agent_<이름>)는 그래프가 따로 그려 뺀다.
    """
    owners: dict[str, list[str]] = {}
    for agent_id, names in tools_by_agent.items():
        for name in names:
            if name.startswith(SUBAGENT_PREFIX):
                continue
            ids = owners.setdefault(name, [])
            if agent_id not in ids:
                ids.append(agent_id)
    return [{"name": n, "agents": ids} for n, ids in sorted(owners.items(), key=lambda kv: (len(kv[1]) > 1, kv[0]))]


def build_workflow_router(state: WebState) -> APIRouter:
    router = APIRouter(tags=["workflow"])
    ctx = state.ctx
    agents = state.assembly.agents

    needs_approval = set(state.settings.security.require_approval_for)

    def capabilities() -> list[dict[str, Any]]:
        # 에이전트마다 세션이 실제로 쓰는 도구(정의의 tools, never 를 거른 것). 세션을 열지 않고 레지스트리만 만든다
        registries = {p.agent_id: agents.tool_registry(p.agent_id) for p in agents.profiles()}
        tools = {aid: [t.name for t in reg.list_all()] for aid, reg in registries.items() if reg is not None}
        described = {t.name: t for reg in registries.values() if reg is not None for t in reg.list_all()}
        return [
            {
                **cap,
                "description": short_description(described[cap["name"]].description),
                "approval": cap["name"] in needs_approval,
            }
            for cap in capability_map(tools)
        ]

    @router.get(
        "/api/workflow",
        summary="에이전트 관계 그래프",
        description=(
            "agents 는 최상위 에이전트, subagents 는 위임 도구(agent_<이름>)로 실린 sub-agent 이름순,"
            " capabilities 는 도구마다 그 도구를 쓰는 에이전트(한 에이전트만 가진 것이 먼저),"
            " edges 는 이 프로세스가 본 최근 위임 200개(오래된 것부터). 끝나지 않은 위임은 ended_ms 와 ok 가 null."
        ),
        responses={200: {"content": {"application/json": {"example": WORKFLOW_EXAMPLE}}}},
    )
    async def get_workflow() -> JSONResponse:
        top = [
            {"id": p.agent_id, "name": p.name, "primary": p.brand.palette.primary, "main": p.is_main}
            for p in agents.profiles()
        ]
        subagents = sorted(
            t.name[len(SUBAGENT_PREFIX):] for t in ctx.tool_registry.list_all() if t.name.startswith(SUBAGENT_PREFIX)
        )
        edges = [e.to_dict() for e in state.workflow.edges()]
        return JSONResponse({"agents": top, "subagents": subagents, "capabilities": capabilities(), "edges": edges})

    @router.get(
        "/api/jobs",
        summary="백그라운드 작업 현황",
        description=(
            "스케줄(돈 적 없는 것도), 성찰 daemon, 기억 정리, 외부 조회의 마지막 실행. 실행 기록은 프로세스 메모리라"
            " 재시작하면 runs 가 0 부터 다시 센다. daemon 은 성찰 주기 설정."
        ),
        responses={200: {"content": {"application/json": {"example": JOBS_EXAMPLE}}}},
    )
    async def get_jobs() -> JSONResponse:
        schedules: list[dict[str, Any]] = []
        if ctx.scheduler is not None:
            from jarvis.core.scheduler.scheduler_service import SchedulerService

            now = datetime.now()
            for task in ctx.scheduler.list_tasks():
                nxt = SchedulerService.next_run(task, now)
                schedules.append({
                    "name": task.name,
                    "label": task.description or task.name,
                    "enabled": task.enabled,
                    "next_run": nxt.astimezone().isoformat() if nxt else None,
                    "agent": task.agent,
                })
            schedules.sort(key=lambda s: str(s["name"]))
        pcfg = state.settings.proactive
        daemon = {
            "enabled": pcfg.daemon_enabled,
            "trigger": pcfg.daemon_trigger,
            "interval_sec": pcfg.daemon_interval_sec,
            "idle_sec": pcfg.daemon_idle_sec,
        }
        return JSONResponse({"jobs": merge_jobs(state.jobs.records(), schedules), "daemon": daemon})

    return router
