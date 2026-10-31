"""[ui] 세션 REST: 목록, 새로 만들기, 분기, 삭제, 이력 조회."""

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse

from jarvis.model_layer.model_types import AssistantMessage, UserMessage
from jarvis.ui.web.web_schema import CreateSessionRequest
from jarvis.ui.web.session_registry import UnknownAgent
from jarvis.ui.web.web_state import WebState

SESSION_ID_DOC = "세션 고유 id. 화면은 8자 hex 를 쓰고 default 는 기동 때 만들어진다"


def build_session_router(state: WebState) -> APIRouter:
    router = APIRouter(tags=["sessions"])
    registry = state.registry

    @router.get(
        "/api/sessions",
        summary="열린 세션 목록",
        description=(
            "이 서버 프로세스가 지금 들고 있는 세션 id 들과 각 세션의 에이전트 id."
            " 재시작하면 기동 세션부터 다시 쌓인다."
        ),
        responses={200: {"content": {"application/json": {"example": {
            "sessions": ["default", "3f9a2c1e"], "agents": {"default": "main", "3f9a2c1e": "karen"},
        }}}}},
    )
    async def list_sessions() -> JSONResponse:
        return JSONResponse({"sessions": registry.list_ids(), "agents": registry.session_agents()})

    @router.post(
        "/api/sessions",
        summary="새 세션 만들기",
        description="8자 hex id 로 저장소에 세션을 만들고 조립해 둔다. 본문이 없으면 main 에이전트의 세션이다.",
        responses={
            200: {"content": {"application/json": {"example": {"session_id": "3f9a2c1e", "agent": "karen"}}}},
            400: {"content": {"application/json": {"example": {"error": "unknown agent: ghost"}}}},
        },
    )
    async def create_session(payload: CreateSessionRequest | None = None) -> JSONResponse:
        agent = payload.agent if payload is not None else None
        try:
            sid = await registry.create_new(agent)
        except UnknownAgent as exc:
            return JSONResponse({"error": f"unknown agent: {exc}"}, status_code=400)
        return JSONResponse({"session_id": sid, "agent": registry.agent_of(sid)})

    @router.post(
        "/api/sessions/{session_id}/branch",
        summary="세션 분기",
        description=(
            "jsonl 저장소면 메시지를 복사한 분기를 만든다. 다른 저장소면 빈 새 세션을 만들고 parent_id 는 null."
            " 어느 쪽이든 분기는 부모와 같은 에이전트다."
        ),
        responses={200: {"content": {"application/json": {"example": {"session_id": "b7c1", "parent_id": "default"}}}}},
    )
    async def branch_session(session_id: str = Path(description=SESSION_ID_DOC, examples=["default"])) -> JSONResponse:
        from jarvis.agent_layer.session.jsonl import JsonlSessionRepo

        repo = state.ctx.session_repo
        if isinstance(repo, JsonlSessionRepo):
            meta = await repo.create_branch(session_id)
        else:
            parent = await repo.get_meta(session_id)
            new_sid = await registry.create_new(parent.agent_id if parent is not None else None)
            return JSONResponse({"session_id": new_sid, "parent_id": None})
        # 분기 세션을 미리 조립해 둔다
        await registry.get_or_create(meta.session_id)
        return JSONResponse({"session_id": meta.session_id, "parent_id": meta.parent_id})

    @router.delete(
        "/api/sessions/{session_id}",
        summary="세션 삭제",
        description="열린 연결이 있으면 409. 없는 세션을 지워도 같은 응답이다.",
        responses={
            200: {"content": {"application/json": {"example": {"deleted": "3f9a2c1e"}}}},
            409: {"content": {"application/json": {"example": {"error": "session has live connections"}}}},
        },
    )
    async def delete_session(session_id: str = Path(description=SESSION_ID_DOC, examples=["3f9a2c1e"])) -> JSONResponse:
        broker = state.approvals.get(session_id)
        if broker is not None and broker.connection_count > 0:
            return JSONResponse({"error": "session has live connections"}, status_code=409)
        await registry.remove(session_id)
        state.approvals.pop(session_id, None)
        return JSONResponse({"deleted": session_id})

    @router.get(
        "/api/sessions/{session_id}/messages",
        summary="세션 이력",
        description="사용자와 비서의 텍스트만 시간순으로. 도구 호출과 결과는 빠진다.",
        responses={
            200: {"content": {"application/json": {"example": {"messages": [{"role": "user", "text": "안녕"}]}}}}
        },
    )
    async def get_session_messages(
        session_id: str = Path(description=SESSION_ID_DOC, examples=["default"]),
    ) -> JSONResponse:
        messages = await state.ctx.session_repo.get_messages(session_id)
        result: list[dict[str, str]] = []
        for msg in messages:
            # role 은 메시지 타입마다 Literal 하나라 isinstance 와 같은 분기다
            if isinstance(msg, UserMessage):
                content = msg.content
                text = content if isinstance(content, str) else "".join(
                    c.text for c in content if hasattr(c, "text")
                )
                if text:
                    result.append({"role": "user", "text": text})
            elif isinstance(msg, AssistantMessage):
                text = msg.text()
                if text:
                    result.append({"role": "assistant", "text": text})
        return JSONResponse({"messages": result})

    return router
