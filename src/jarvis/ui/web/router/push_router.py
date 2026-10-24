"""[ui] 앱 Web Push REST: VAPID 공개키 조회와 구독 등록, 해제."""

from typing import Any
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from jarvis.ui.web.web_auth import bearer_token, lookup_api_user
from jarvis.core.notify.webpush import validate_subscription
from jarvis.ui.web.web_state import WebState

PUSH_DISABLED = {"error": "push disabled"}


def build_push_router(state: WebState) -> APIRouter:
    router = APIRouter(tags=["push"])
    cfg = state.settings.notify

    def enabled() -> bool:
        return state.ctx.push_store is not None and bool(cfg.webpush_vapid_public_key)

    async def body_of(request: Request) -> dict[str, Any] | None:
        try:
            data = await request.json()
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    @router.get(
        "/api/push/vapid",
        summary="Web Push 공개키",
        description="앱이 구독할 때 쓰는 VAPID 공개키(base64url, 패딩 없음). 키나 Postgres 가 없으면 404.",
        responses={
            200: {"content": {"application/json": {"example": {"public_key": "BEl62iUYgUivxIkv69yViEuiBIa-Ib9-..."}}}},
            404: {"content": {"application/json": {"example": PUSH_DISABLED}}},
        },
    )
    async def vapid() -> JSONResponse:
        if not enabled():
            return JSONResponse(PUSH_DISABLED, status_code=404)
        return JSONResponse({"public_key": cfg.webpush_vapid_public_key})

    @router.put(
        "/api/push/subscriptions",
        summary="Web Push 구독 등록",
        description="브라우저 PushSubscription.toJSON() 을 그대로 받는다. endpoint 가 자연 키라 행은 하나다.",
        responses={
            200: {"content": {"application/json": {"example": {"ok": True}}}},
            400: {"content": {"application/json": {"example": {"error": "endpoint must start with https://"}}}},
            404: {"content": {"application/json": {"example": PUSH_DISABLED}}},
        },
    )
    async def subscribe(request: Request) -> JSONResponse:
        store = state.ctx.push_store
        if store is None or not enabled():
            return JSONResponse(PUSH_DISABLED, status_code=404)
        data = await body_of(request)
        if data is None:
            return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
        try:
            sub = validate_subscription(data)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        user = lookup_api_user(state.settings, bearer_token(request.headers.get("authorization")))
        await store.upsert(sub, user.name if user is not None else None)
        return JSONResponse({"ok": True})

    @router.delete(
        "/api/push/subscriptions",
        summary="Web Push 구독 해제",
        description="endpoint 의 구독을 지운다. 없는 endpoint 도 200 이다.",
        responses={
            200: {"content": {"application/json": {"example": {"ok": True}}}},
            400: {"content": {"application/json": {"example": {"error": "endpoint is required"}}}},
            404: {"content": {"application/json": {"example": PUSH_DISABLED}}},
        },
    )
    async def unsubscribe(request: Request) -> JSONResponse:
        store = state.ctx.push_store
        if store is None or not enabled():
            return JSONResponse(PUSH_DISABLED, status_code=404)
        data = await body_of(request)
        endpoint = str((data or {}).get("endpoint") or "")
        if not endpoint:
            return JSONResponse({"error": "endpoint is required"}, status_code=400)
        await store.delete(endpoint)
        return JSONResponse({"ok": True})

    return router
