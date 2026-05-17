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
    """Web HUD 서버 실행. ctx/extra를 SessionManager에 위임하여 다중 세션을 지원한다."""
    import uvicorn

    from jarvis.ui.web.server import create_app

    app = create_app(
        ctx=ctx,
        base_extra=extra,
        initial_session_id=session_id or "default",
    )

    print(f"[Jarvis] Web HUD started → http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
