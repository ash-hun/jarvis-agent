"""[ui] AGENDA REST: 스케줄과 열린 약속 조회, 약속 닫기, 스케줄 켜고 끄기."""

import time
from datetime import datetime

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse

from jarvis.agent_layer.openloop import close_expired
from jarvis.ui.web.web_schema import OpenLoopStatusRequest, ScheduleToggleRequest
from jarvis.ui.web.web_state import WebState

# AGENDA 카드가 보여 주는 열린 약속 수
AGENDA_LOOP_LIMIT = 20
PROMPT_PREVIEW_CHARS = 160


def build_agenda_router(state: WebState) -> APIRouter:
    router = APIRouter(tags=["agenda"])
    ctx = state.ctx

    @router.get(
        "/api/agenda",
        summary="AGENDA 카드 내용",
        description="스케줄(곧 돌 것이 위)과 열린 약속(최신순 20개). 기한이 지난 약속은 응답 전에 expired 로 닫힌다.",
        responses={200: {"content": {"application/json": {"example": {
            "schedules": [],
            "open_loops": [{"id": "e17d", "description": "회의 준비", "due_ms": None, "created_at": 1791613276663,
                            "origin_session": "default"}],
        }}}}},
    )
    async def get_agenda() -> JSONResponse:
        schedules: list[dict[str, object]] = []
        if ctx.scheduler is not None:
            from jarvis.core.scheduler.service import SchedulerService

            now = datetime.now()
            for task in ctx.scheduler.list_tasks():
                nxt = SchedulerService.next_run(task, now)
                schedules.append({
                    "name": task.name,
                    "description": task.description,
                    "prompt": task.prompt[:PROMPT_PREVIEW_CHARS],
                    "schedule": task.schedule,
                    "kind": task.kind,
                    "once": task.run_at is not None,
                    "enabled": task.enabled,
                    # 서버 로컬 시간대 오프셋을 붙인다. 브라우저가 어느 시간대에 있든 같은 순간을 가리키게
                    "next_run": nxt.astimezone().isoformat() if nxt else None,
                    "run_until": task.run_until.astimezone().isoformat() if task.run_until else None,
                })
            # 곧 돌 작업이 위로, 다음 실행이 없는(꺼짐, 만료) 작업은 아래로
            schedules.sort(key=lambda t: (t["next_run"] is None, str(t["next_run"] or ""), str(t["name"])))

        loops: list[dict[str, object]] = []
        store = state.assembly.services.openloop_store
        if store is not None:
            # 화면이 사고 tick 을 기다리지 않고 지난 약속을 내리게, 목록을 줄 때도 만료를 맞춘다
            cfg = state.settings.openloop
            await close_expired(store, int(time.time() * 1000), cfg.expire_after_sec * 1000, cfg.max_age_sec * 1000)
            for loop in await store.list_open(limit=AGENDA_LOOP_LIMIT):
                loops.append({
                    "id": loop.id,
                    "description": loop.description,
                    "due_ms": loop.due_ms,
                    "created_at": loop.created_at,
                    "origin_session": loop.origin_session,
                })
        return JSONResponse({"schedules": schedules, "open_loops": loops})

    @router.post(
        "/api/openloops/{loop_id}",
        summary="약속 닫기",
        description="열린 약속을 완료(done) 또는 무시(dismissed)로 닫는다. 같은 값을 다시 보내도 결과가 같다.",
        responses={
            200: {"content": {"application/json": {"example": {"id": "e17d", "status": "done"}}}},
            400: {"content": {"application/json": {"example": {"error": "status must be 'done' or 'dismissed'"}}}},
            404: {"content": {"application/json": {"example": {"error": "open loop not found"}}}},
        },
    )
    async def update_openloop(
        payload: OpenLoopStatusRequest,
        loop_id: str = Path(description="GET /api/agenda 가 준 약속 id", examples=["e17d"]),
    ) -> JSONResponse:
        status = payload.status
        if status not in ("done", "dismissed"):
            return JSONResponse({"error": "status must be 'done' or 'dismissed'"}, status_code=400)
        store = state.assembly.services.openloop_store
        if store is None or not await store.update_status(loop_id, str(status)):
            return JSONResponse({"error": "open loop not found"}, status_code=404)
        return JSONResponse({"id": loop_id, "status": status})

    @router.post(
        "/api/schedules/{name}",
        summary="스케줄 켜고 끄기",
        description="작업 파일의 enabled 만 바꾼다.",
        responses={
            200: {"content": {"application/json": {"example": {"name": "morning-brief", "enabled": False}}}},
            400: {"content": {"application/json": {"example": {"error": "enabled must be true or false"}}}},
            404: {"content": {"application/json": {"example": {"error": "schedule not found"}}}},
        },
    )
    async def toggle_schedule(
        payload: ScheduleToggleRequest,
        name: str = Path(description="스케줄 작업 이름(파일 이름)", examples=["morning-brief"]),
    ) -> JSONResponse:
        enabled = payload.enabled
        if not isinstance(enabled, bool):
            return JSONResponse({"error": "enabled must be true or false"}, status_code=400)
        if ctx.scheduler is None or not ctx.scheduler.set_enabled(name, enabled):
            return JSONResponse({"error": "schedule not found"}, status_code=404)
        return JSONResponse({"name": name, "enabled": enabled})

    return router
