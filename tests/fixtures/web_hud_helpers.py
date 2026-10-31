"""Web HUD 통합 테스트가 같이 쓰는 앱 조립, 프로바이더 끼우기, 한 턴 받기 도우미."""

import time
import pytest
from typing import Any
from pathlib import Path
from collections.abc import Iterator
from fastapi.testclient import TestClient

from jarvis.model_layer.model_registry import get_default_registry
from jarvis.app.app_assembly import AppAssembly
from jarvis.jarvis_config import JarvisSettings
from jarvis.app.infra_builder import build_app
from jarvis.ui.web.server import create_app

TEAM_DIR = Path(__file__).resolve().parents[2] / "team"


def web_assembly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str) -> AppAssembly:
    """백그라운드 루프와 실 DB 없이 앱을 조립한다. env 는 JARVIS_ 뒤의 키로 덧붙인다."""
    # .env 가 postgres 백엔드를 주입하므로 메모리와 jsonl 로 고정한다
    base = {
        "PROACTIVE__DAEMON_ENABLED": "false",
        "SCHEDULER__ENABLED": "false",
        "MEMORY__BACKEND": "in_memory",
        "SESSION__PERSISTENCE_BACKEND": "jsonl",
        "SESSION__SESSIONS_DIR": str(tmp_path / "sessions"),
    }
    for key, value in {**base, **env}.items():
        monkeypatch.setenv(f"JARVIS_{key}", value)
    return build_app(JarvisSettings())


def web_client(assembly: AppAssembly) -> TestClient:
    return TestClient(create_app(assembly, initial_session_id="default"))


def scripted_env(provider: str, tmp_path: Path, team_dir: Path = TEAM_DIR) -> dict[str, str]:
    """각본 프로바이더로 팀 에이전트를 돌리는 설정."""
    return {
        "TEAM__DIR": str(team_dir),
        "LLM__PROVIDER": provider,
        "LLM__MODEL": f"{provider}-1",
        "THOUGHT__ENABLED": "false",
        "SECURITY__AGENT_APPROVALS_DIR": str(tmp_path / "approvals"),
    }


def use_provider(provider: Any) -> Iterator[Any]:
    """기본 레지스트리에 각본 프로바이더를 끼웠다가 테스트가 끝나면 뺀다. fixture 본문으로 쓴다."""
    registry = get_default_registry()
    registry._providers[provider.provider_name] = provider
    yield provider
    registry._providers.pop(provider.provider_name, None)


def run_turn(ws: Any, text: str) -> list[dict]:
    """루트 agent_end 까지 받은 메시지 전부.

    agent_end 직후에는 세션이 아직 바쁨 표시를 끄기 전일 수 있다. 그때 온 '처리 중' 오류면 잠깐 쉬고 다시 보낸다.
    """
    seen = []
    ws.send_json({"type": "user_message", "text": text})
    while True:
        msg = ws.receive_json()
        seen.append(msg)
        if msg["type"] == "agent_end":
            return seen
        if msg["type"] == "error" and "처리 중" in msg["message"]:
            time.sleep(0.1)
            ws.send_json({"type": "user_message", "text": text})


def reply_text(seen: list[dict], kinds: tuple[str, ...] = ("message_update",)) -> str:
    return "".join(m.get("text_delta", "") or m.get("text", "") for m in seen if m["type"] in kinds)


def agenda_assembly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[AppAssembly, Any]:
    """open loop 는 메모리, 스케줄러는 cron 루프 없이 tmp 디렉토리를 쓰는 앱. 작업은 late(켜짐), off(꺼짐)."""
    from unittest.mock import AsyncMock, MagicMock

    from jarvis.core.scheduler.scheduler_service import SchedulerService
    from jarvis.core.scheduler.task import ScheduledTask

    assembly = web_assembly(monkeypatch, tmp_path, THOUGHT__ENABLED="true", OPENLOOP__BACKEND="in_memory")
    scheduler = SchedulerService(
        tasks=[
            ScheduledTask(name="late", schedule="0 23 * * *", prompt="late job"),
            ScheduledTask(name="off", schedule="0 9 * * *", prompt="off job", enabled=False),
        ],
        session_repo=MagicMock(),
        tool_registry=MagicMock(),
        model=MagicMock(),
        schedules_dir=str(tmp_path / "schedules"),
    )
    scheduler.start = AsyncMock()  # type: ignore[method-assign]
    assembly.ctx.scheduler = scheduler
    return assembly, scheduler
