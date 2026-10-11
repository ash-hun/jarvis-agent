"""[ui] Web HUD FastAPI 앱 조립: 상태, 인증 미들웨어, 기동과 종료, 라우터, 정적 셸을 하나로 묶는다."""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from jarvis.ui.web.router.agenda_router import build_agenda_router
from jarvis.ui.web.router.brand_router import STATIC_DIR, build_brand_router
from jarvis.ui.web.router.session_router import build_session_router
from jarvis.ui.web.router.tool_router import build_tool_router
from jarvis.ui.web.router.ws_router import build_ws_router
from jarvis.ui.web.web_auth import auth_enabled, bearer_token, lookup_api_user
from jarvis.ui.web.web_lifecycle import WebLifecycle
from jarvis.ui.web.web_state import WebState

if TYPE_CHECKING:
    from jarvis.app.app_assembly import AppAssembly

__all__ = ["STATIC_DIR", "create_app"]


def create_app(assembly: "AppAssembly", initial_session_id: str = "default") -> FastAPI:
    app = FastAPI(title="Jarvis HUD", docs_url=None, redoc_url=None)
    state = WebState(assembly)
    lifecycle = WebLifecycle(state, initial_session_id)
    settings = state.settings

    @app.middleware("http")
    async def require_api_key(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # /api/* 만 보호한다. 정적 셸(index, js, css)은 키 없이 받아야 키 입력 화면이 뜬다
        if request.url.path.startswith("/api/") and auth_enabled(settings):
            token = bearer_token(request.headers.get("authorization")) or request.query_params.get("token")
            if lookup_api_user(settings, token) is None:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        response = await call_next(request)
        # 정적 셸은 매번 재검증(ETag). nginx 설정과 같은 이유: 고친 js/css 가 바로 보여야 한다
        if not request.url.path.startswith("/api/") and "cache-control" not in response.headers:
            response.headers["cache-control"] = "no-cache"
        return response

    app.router.add_event_handler("startup", lifecycle.start)
    app.router.add_event_handler("shutdown", lifecycle.stop)

    app.include_router(build_session_router(state))
    app.include_router(build_tool_router(state))
    app.include_router(build_agenda_router(state))
    app.include_router(build_ws_router(state))
    app.include_router(build_brand_router(state))

    # 정적 파일은 API 와 WebSocket 라우트를 다 단 뒤에 마운트한다(앞에 두면 / 가 모두 가로챈다)
    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    return app
