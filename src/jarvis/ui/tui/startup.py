"""[ui] jarvis 명령의 진입점. CLI 인자를 StartupPlan 으로 정규화하고 TUI 나 Web 을 띄운다."""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from jarvis.common.logger import get_logger

if TYPE_CHECKING:
    from jarvis.app.app_assembly import AppAssembly
    from jarvis.config import JarvisSettings
    from jarvis.core.session import AgentSession
    from jarvis.ui.tui.voice import TuiVoiceController

logger = get_logger(__name__)
# 에이전트를 정하지 않고 시작하면 붙는 세션. main 의 예전 고정 세션 이름이다
DEFAULT_SESSION_ID = "default"


# ── StartupPlan (Hunk: Startup Planner 패턴) ──────────────────────────────────


@dataclass(frozen=True)
class TUIPlan:
    kind: Literal["tui"]
    session_id: str | None = None
    agent: str | None = None


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
class SessionResumePlan:
    kind: Literal["session-resume"]
    session_id: str


@dataclass(frozen=True)
class WebPlan:
    kind: Literal["web"]
    session_id: str | None = None
    host: str = "127.0.0.1"
    port: int = 7777


StartupPlan = TUIPlan | HelpPlan | VersionPlan | SessionListPlan | SessionResumePlan | WebPlan


def parse_startup_plan(argv: list[str] | None = None) -> StartupPlan:
    """
    모든 CLI 입력을 렌더링 전에 StartupPlan으로 정규화.
    순수 함수 — 단위 테스트 가능. Hunk: Startup Planner 패턴.
    """
    args = argv if argv is not None else sys.argv[1:]

    parser = argparse.ArgumentParser(prog="jarvis", add_help=False)
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("--version", "-v", action="store_true")
    parser.add_argument("--list-sessions", action="store_true")
    parser.add_argument("--session", "-s", type=str, default=None)
    parser.add_argument("--agent", "-a", type=str, default=None)
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
    if parsed.web:
        return WebPlan(kind="web", session_id=parsed.session, host=parsed.host, port=parsed.port)
    if parsed.session:
        return SessionResumePlan(kind="session-resume", session_id=parsed.session)
    return TUIPlan(kind="tui", session_id=None, agent=parsed.agent)


# ── main() 진입점 ─────────────────────────────────────────────────────────────

HELP_TEXT = (
    "Usage: jarvis [OPTIONS]\n\n"
    "Options:\n"
    "  -s, --session ID       기존 세션 재개(세션을 만든 에이전트로 열린다)\n"
    "  -a, --agent ID         이 에이전트의 기본 세션으로 시작 (예: karen, 기본 main)\n"
    "  --list-sessions        저장된 세션 목록 출력\n"
    "  --web                  Web HUD 모드 실행\n"
    "  --host HOST            Web 서버 호스트 (기본: 127.0.0.1)\n"
    "  --port PORT            Web 서버 포트 (기본: 7777)\n"
    "  -v, --version          버전 출력\n"
    "  -h, --help             이 도움말 출력\n"
)


def build_tui_voice(settings: "JarvisSettings") -> "TuiVoiceController | None":
    """voice.tui_enabled 일 때만. 프로바이더 import 가 실패하면 음성 없이 계속한다."""
    vcfg = settings.voice
    if not vcfg.tui_enabled:
        return None
    try:
        from jarvis.ui.tui.voice import TuiVoiceController
        from jarvis.voice.service import VoiceService

        service = VoiceService.from_config(stt_provider=vcfg.stt_provider, tts_provider=vcfg.tts_provider)
        return TuiVoiceController(service)
    except Exception as exc:
        logger.info(f"[Voice] TUI 음성 비활성화 (초기화 실패): {exc}")
        return None


async def save_session_end(assembly: "AppAssembly", session: "AgentSession") -> None:
    """TUI 종료 후 세션 요약, 사실 공고화, 절차 학습. 이력은 session_repo 가 정본이다. 실패해도 종료를 막지 않는다."""
    from jarvis.app.session_builder import learn_procedures

    ctx, services = assembly.ctx, assembly.services
    try:
        msgs = await ctx.session_repo.get_messages(session._session_id)
        if not msgs:
            return
        from jarvis.memory.consolidation.episodic import EpisodicSummarizer

        summarizer = EpisodicSummarizer(model=services.model_config, memory=services.memory)
        entry_id = await summarizer.save_session(session._session_id, msgs, scope=session.memory_scope)
        if entry_id:
            logger.info(f"[Episodic] Session summary saved (id: {entry_id[:8]})")
        facts = await services.memory.consolidate(session.memory_scope)
        if facts:
            logger.info(f"[Memory] {facts} fact(s) consolidated from this session")
        learned = await learn_procedures(ctx, session._session_id, msgs)
        if learned:
            logger.info(f"[Procedures] draft(s) saved: {', '.join(learned)} (approve: /procedures approve <name>)")
    except Exception as exc:
        logger.info(f"[Episodic] Session summary failed (non-fatal): {exc}")


async def resolve_tui_session(
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


def main() -> None:
    from jarvis.app.infra_builder import build_app
    from jarvis.config import get_settings

    plan = parse_startup_plan()
    if plan.kind == "help":
        print(HELP_TEXT)
        return
    if plan.kind == "version":
        print("jarvis 0.1.0")
        return

    settings = get_settings()
    assembly = build_app(settings)
    ctx = assembly.ctx

    if plan.kind == "session-list":

        async def _print_sessions() -> None:
            sessions = await ctx.session_repo.list()
            if not sessions:
                print("저장된 세션 없음")
                return
            for s in sessions:
                print(f"{s.session_id}")

        asyncio.run(_print_sessions())
        return

    if plan.kind == "web":
        from jarvis.ui.web.startup import run_web

        run_web(assembly, session_id=plan.session_id or "default", host=plan.host, port=plan.port)
        return

    # TUIPlan or SessionResumePlan → TUI 실행
    from jarvis.ui.tui.app import JarvisTUI

    try:
        agent_id, session_id = asyncio.run(
            resolve_tui_session(assembly, getattr(plan, "session_id", None), getattr(plan, "agent", None))
        )
    except ValueError as exc:
        print(exc)
        return
    builder = assembly.agents.builder(agent_id)
    ctx.session_factory = builder.new_session_factory()
    ctx.branch_factory = builder.branch_factory()
    session = builder.build(session_id)
    app = JarvisTUI(session=session, ctx=ctx, voice_controller=build_tui_voice(settings))
    # 승인 다이얼로그를 sandbox 의 approval_callback 으로 연결
    assembly.services.sandbox.set_approval_callback(app.request_approval)
    app.run()
    asyncio.run(save_session_end(assembly, session))
