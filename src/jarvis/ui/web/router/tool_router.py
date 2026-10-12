"""[ui] 도구와 슬래시 명령 목록 REST. SYSTEM 카드와 입력창 / 팝업이 쓴다."""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from jarvis.ui.web.web_state import WebState

TOOL_DESCRIPTION_CHARS = 160


def build_tool_router(state: WebState) -> APIRouter:
    router = APIRouter(tags=["tools"])
    ctx = state.ctx

    @router.get(
        "/api/slash-commands",
        summary="슬래시 명령 목록",
        description="이름순. 입력창의 / 자동완성 팝업이 쓴다. 디스패처가 없으면 빈 목록.",
        responses={200: {"content": {"application/json": {"example": {
            "commands": [{"name": "remember", "description": "내용 저장/검색/삭제"}]}}}}},
    )
    async def get_slash_commands() -> JSONResponse:
        if ctx.dispatcher is None:
            return JSONResponse({"commands": []})
        cmds = [{"name": name, "description": desc} for name, desc in sorted(ctx.dispatcher.commands.items())]
        return JSONResponse({"commands": cmds})

    @router.get(
        "/api/tools",
        summary="도구 목록",
        description=(
            "이름순. 설명은 첫 줄 160자, approval 은 실행 전 승인이 필요한지."
            " session_id 를 주면 그 세션 에이전트가 쓰는 도구만, 없거나 열리지 않은 세션이면 앱 전체 도구."
        ),
        responses={200: {"content": {"application/json": {"example": {
            "tools": [{"name": "bash", "description": "셸 명령 실행", "approval": True}]}}}}},
    )
    async def list_tools(
        session_id: str | None = Query(default=None, description="열린 세션 id", examples=["default"]),
    ) -> JSONResponse:
        registry = (state.registry.tool_registry_of(session_id) if session_id else None) or ctx.tool_registry
        needs_approval = set(state.settings.security.require_approval_for)
        tools = [
            {
                "name": tool.name,
                "description": (tool.description or "").strip().split("\n")[0][:TOOL_DESCRIPTION_CHARS],
                "approval": tool.name in needs_approval,
            }
            for tool in sorted(registry.list_all(), key=lambda t: t.name)
        ]
        return JSONResponse({"tools": tools})

    return router
