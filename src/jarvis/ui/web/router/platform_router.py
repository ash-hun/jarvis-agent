"""[ui] 플랫폼 지표 REST: Ion 가 백엔드 프로세스와 에이전트별 작업 상태를 읽는다."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from jarvis.ui.web.web_state import WebState

METRICS_EXAMPLE = {
    "at_ms": 1794500000000,
    "process": {"pid": 1, "rss_bytes": 231735296, "cpu_percent": 1.5, "threads": 12, "open_fds": 48,
                "asyncio_tasks": 9, "uptime_sec": 86400.0},
    "loop_lag": {"last_ms": 0.4, "max_ms": 12.0, "samples": 60},
    "agents": [
        {"agent": "karen", "jobs": 1, "running": 0, "fail_streak": 0, "last_ok_ms": 1794499200000,
         "last_error": "", "open_sessions": 0, "scheduled": True, "last_active_ms": 1794499200000,
         "proactive": True},
        {"agent": "main", "jobs": 0, "running": 0, "fail_streak": 0, "last_ok_ms": None, "last_error": "",
         "open_sessions": 1, "scheduled": False, "last_active_ms": 1794499980000, "proactive": True},
        {"agent": "shared", "jobs": 2, "running": 0, "fail_streak": 0, "last_ok_ms": 1794499980000,
         "last_error": "", "open_sessions": 0, "scheduled": False, "last_active_ms": None, "proactive": False},
    ],
}


def build_platform_router(state: WebState) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/api/platform/metrics",
        summary="플랫폼 지표",
        description=(
            "백엔드 프로세스 자원(RSS, CPU, 스레드, fd, asyncio 작업, 가동 시간), 이벤트 루프 지연(최근 60초 최대),"
            " 에이전트별 작업 상태(작업 수, 도는 중, 연속 실패, 마지막 성공 시각, 열린 세션 수, 켜진 스케줄 유무,"
            " 마지막 활동 시각, 먼저 말을 거는지)."
            " 스케줄 작업은 그 작업의 에이전트로, 성찰과 기억 정리처럼 프로세스 전체의 일은 shared 로 센다."
        ),
        responses={200: {"content": {"application/json": {"example": METRICS_EXAMPLE}}}},
    )
    async def get_metrics() -> JSONResponse:
        return JSONResponse(state.platform_metrics.snapshot(await state.last_active()))

    return router
