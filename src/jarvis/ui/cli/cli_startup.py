"""[ui] jarvis 명령의 진입점. CLI 인자를 StartupPlan 으로 정규화하고 Web HUD 백엔드를 띄운다."""

import sys
import asyncio
import argparse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from jarvis.common.logger import get_logger

if TYPE_CHECKING:
    from jarvis.app.app_assembly import AppAssembly

logger = get_logger(__name__)
# 에이전트를 정하지 않고 시작하면 붙는 세션. main 의 예전 고정 세션 이름이다
DEFAULT_SESSION_ID = "default"
HELP_TEXT = (
    "Usage: jarvis [OPTIONS]\n\n"
    "Web HUD 백엔드를 띄운다. 화면은 브라우저나 데스크톱 앱(desktop/)으로 연다.\n\n"
    "Options:\n"
    "  -s, --session ID       이 세션으로 화면을 연다(세션을 만든 에이전트로 열린다)\n"
    "  -a, --agent ID         이 에이전트의 기본 세션으로 연다 (예: karen, 기본 main)\n"
    "  --list-sessions        저장된 세션 목록 출력\n"
    "  --host HOST            서버 호스트 (기본: 127.0.0.1)\n"
    "  --port PORT            서버 포트 (기본: 7777)\n"
    "  -v, --version          버전 출력\n"
    "  -h, --help             이 도움말 출력\n"
)


@dataclass(frozen=True)
class HelpPlan:
    kind: Literal["help"]


@dataclass(frozen=True)
class VersionPlan:
    kind: Literal["version"]


@dataclass(frozen=True)
class SessionListPlan:
    kind: Literal["session-list"]


@dataclass(frozen=True)
class WebPlan:
    kind: Literal["web"]
    session_id: str | None = None
    agent: str | None = None
    host: str = "127.0.0.1"
    port: int = 7777


StartupPlan = HelpPlan | VersionPlan | SessionListPlan | WebPlan


def parse_startup_plan(argv: list[str] | None = None) -> StartupPlan:
    """CLI 입력을 실행 전에 StartupPlan 하나로 정규화한다. 모르는 인자는 무시한다."""
    args = argv if argv is not None else sys.argv[1:]

    parser = argparse.ArgumentParser(prog="jarvis", add_help=False)
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("--version", "-v", action="store_true")
    parser.add_argument("--list-sessions", action="store_true")
    parser.add_argument("--session", "-s", type=str, default=None)
    parser.add_argument("--agent", "-a", type=str, default=None)
    # 예전 진입점과 Dockerfile 이 넘기는 플래그. 이제 기본 동작이라 받기만 한다
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7777)

    parsed, _ = parser.parse_known_args(args)

    if parsed.help:
        return HelpPlan(kind="help")
    if parsed.version:
        return VersionPlan(kind="version")
    if parsed.list_sessions:
        return SessionListPlan(kind="session-list")
    return WebPlan(kind="web", session_id=parsed.session, agent=parsed.agent, host=parsed.host, port=parsed.port)


async def resolve_start_session(
    assembly: "AppAssembly", session_id: str | None, agent: str | None
) -> tuple[str, str]:
    """(에이전트 id, 세션 id). 있는 세션은 저장된 에이전트로, 새로 시작하면 에이전트의 기본 세션을 만든다."""
    agents = assembly.agents
    repo = assembly.ctx.session_repo
    if session_id is not None:
        meta = await repo.get_meta(session_id)
        agent_id = meta.agent_id if meta is not None else (agent or agents.main.agent_id)
    else:
        agent_id = agent or agents.main.agent_id
        # 에이전트마다 기본 세션 하나. main 은 예전 이름(default)을 지킨다
        session_id = DEFAULT_SESSION_ID if agent_id == agents.main.agent_id else f"{DEFAULT_SESSION_ID}-{agent_id}"
    if agent_id not in agents:
        raise ValueError(f"알 수 없는 에이전트: {agent_id} (있는 에이전트: {', '.join(agents.ids())})")
    await repo.create(session_id=session_id, agent_id=agent_id)
    return agent_id, session_id


async def _print_sessions(assembly: "AppAssembly") -> None:
    sessions = await assembly.ctx.session_repo.list()
    if not sessions:
        print("저장된 세션 없음")
        return
    for s in sessions:
        print(f"{s.session_id}")


def main() -> None:
    from jarvis.common.app_version import app_version
    from jarvis.app.infra_builder import build_app
    from jarvis.jarvis_config import get_settings
    from jarvis.ui.web.startup import run_web

    plan = parse_startup_plan()
    if plan.kind == "help":
        print(HELP_TEXT)
        return
    if plan.kind == "version":
        print(f"jarvis {app_version()}")
        return

    assembly = build_app(get_settings())
    if plan.kind == "session-list":
        asyncio.run(_print_sessions(assembly))
        return

    try:
        _, session_id = asyncio.run(resolve_start_session(assembly, plan.session_id, plan.agent))
    except ValueError as exc:
        print(exc)
        return
    run_web(assembly, session_id=session_id, host=plan.host, port=plan.port)
