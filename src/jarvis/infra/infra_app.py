"""[infra] Infra Agent 의 HTTP: 상태, 사고 목록, 사고 응답, SSE 이벤트. 앱은 nginx 의 /infra/ 로 붙는다."""

import asyncio
import contextlib
from typing import Any
from fastapi import FastAPI, Request
from collections.abc import AsyncIterator
from fastapi.responses import JSONResponse, StreamingResponse

from jarvis.infra.watch_service import ACTIONS, WatchService, sse_line

QUEUE_MAX = 100


class EventHub:
    """열린 SSE 연결마다 큐 하나. 느린 연결은 오래된 이벤트를 버린다."""

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[dict[str, Any]]] = set()

    async def publish(self, payload: dict[str, Any]) -> None:
        for queue in list(self._queues):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(payload)

    async def stream(self) -> AsyncIterator[str]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(QUEUE_MAX)
        self._queues.add(queue)
        try:
            yield sse_line({"type": "hello"})
            while True:
                yield sse_line(await queue.get())
        finally:
            self._queues.discard(queue)


def _token_of(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return request.query_params.get("token")


def build_infra_app(service: WatchService, hub: EventHub, access_key: str | None) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await service.start()
        yield
        await service.stop()

    app = FastAPI(title="Jarvis Infra", docs_url=None, redoc_url=None, lifespan=lifespan)

    @app.middleware("http")
    async def check_key(request: Request, call_next: Any) -> Any:
        if access_key and _token_of(request) != access_key:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.get("/infra/status", summary="플랫폼 상태")
    async def status() -> JSONResponse:
        return JSONResponse(service.status())

    @app.get("/infra/incidents", summary="열린 사고")
    async def incidents() -> JSONResponse:
        return JSONResponse({"incidents": service.status()["incidents"]})

    @app.post("/infra/incidents/{incident_id}/respond", summary="사고에 답하기")
    async def respond(incident_id: str, request: Request) -> JSONResponse:
        body = await request.json() if await request.body() else {}
        action = str(body.get("action") or "")
        if action not in ACTIONS:
            return JSONResponse({"error": f"action must be one of {list(ACTIONS)}"}, status_code=400)
        incident = await service.respond(incident_id, action)
        if incident is None:
            return JSONResponse({"error": "unknown incident"}, status_code=404)
        await hub.publish({"type": "incident_update", "incident": incident.__dict__})
        return JSONResponse({"incident": incident.__dict__})

    @app.get("/infra/events", summary="사고 이벤트(SSE)")
    async def events() -> StreamingResponse:
        return StreamingResponse(hub.stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app
