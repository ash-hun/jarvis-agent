from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jarvis.ui.tui.startup import AppContext


def run_web(
    ctx: AppContext,
    extra: dict[str, Any],
    session_id: str,
    host: str = "127.0.0.1",
    port: int = 7777,
) -> None:
    """
    Web HUD 서버 실행.
    tui/startup._build_infra()로 생성한 ctx, extra를 재사용.
    """
    import uvicorn

    from jarvis.ui.tui.startup import _build_agent_session
    from jarvis.ui.web.adapter import WebUIAdapter
    from jarvis.ui.web.server import create_app

    adapter = WebUIAdapter()
    session = _build_agent_session(session_id, ctx, extra)

    # approval 콜백을 WebUIAdapter로 연결
    extra["sandbox"].set_approval_callback(adapter.request_approval)

    # 에이전트 이벤트를 WebSocket으로 브로드캐스트
    session.subscribe(adapter.on_agent_event)

    app = create_app(session=session, adapter=adapter)

    print(f"[Jarvis] Web HUD started → http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
