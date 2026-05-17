from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

if TYPE_CHECKING:
    from jarvis.core.session import AgentSession
    from jarvis.ui.web.adapter import WebUIAdapter

STATIC_DIR = Path(__file__).parent / "static"


def create_app(session: AgentSession, adapter: WebUIAdapter) -> FastAPI:
    """
    FastAPI 앱을 생성하고 WebSocket 엔드포인트와 static 서빙을 설정.
    session과 adapter는 startup.py에서 주입.
    """
    app = FastAPI(title="Jarvis HUD", docs_url=None, redoc_url=None)

    @app.websocket("/ws")  # type: ignore[untyped-decorator]
    async def websocket_endpoint(ws: WebSocket) -> None:
        await adapter.connect(ws)

        # 연결 직후 세션 정보 전송
        await ws.send_json({"type": "connected", "session_id": session._session_id})

        try:
            while True:
                msg = await ws.receive_json()
                msg_type = msg.get("type", "")

                if msg_type == "user_message":
                    text = msg.get("text", "").strip()
                    if text:
                        asyncio.create_task(_run_prompt(session, adapter, text))

                elif msg_type == "approval_response":
                    await adapter.handle_approval_response(
                        approval_id=msg.get("id", ""),
                        approved=bool(msg.get("approved", False)),
                    )

                elif msg_type == "abort":
                    session.abort()

        except WebSocketDisconnect:
            await adapter.disconnect(ws)
        except Exception:
            await adapter.disconnect(ws)

    # static 파일 서빙 (index.html 포함) — WebSocket 라우트 등록 후 마운트
    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app


async def _run_prompt(session: AgentSession, adapter: WebUIAdapter, text: str) -> None:
    """에이전트 프롬프트 실행 — WebSocket 태스크에서 분리."""
    try:
        await session.prompt(text)
    except Exception as exc:
        await adapter.show_error(str(exc))
