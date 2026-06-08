from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from jarvis.agent_layer.session.protocol import SessionRepo
    from jarvis.config import JarvisSettings
    from jarvis.core.scheduler.service import SchedulerService
    from jarvis.core.session import AgentSession
    from jarvis.core.slash.dispatcher import SlashCommandDispatcher
    from jarvis.core.tools.registry import ToolRegistry


# ── StartupPlan (Hunk: Startup Planner 패턴) ──────────────────────────────────


@dataclass(frozen=True)
class TUIPlan:
    kind: Literal["tui"]
    session_id: str | None = None


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
    return TUIPlan(kind="tui", session_id=None)


# ── AppContext (Warp: AppContext 패턴) ─────────────────────────────────────────


@dataclass
class AppContext:
    """
    JarvisTUI에 전달되는 인프라 컨테이너.
    Warp: AppContext — 렌더/이벤트 처리 중 임시 접근을 위한 컨테이너.
    JarvisTUI.__init__()에 ctx 이름으로 전달 (마지막 파라미터).
    """

    session_repo: SessionRepo
    tool_registry: ToolRegistry
    settings: JarvisSettings
    # Ctrl+N 새 세션 팩토리 — main()에서 주입
    session_factory: Callable[[], Awaitable[AgentSession]] | None = field(default=None)
    # Ctrl+F 브랜치 팩토리 — main()에서 주입
    branch_factory: Callable[[str], Awaitable[AgentSession]] | None = field(default=None)
    # 스케줄러 서비스 — _build_infra()에서 주입
    scheduler: SchedulerService | None = field(default=None)
    # 슬래시 명령 디스패처 — _build_infra()에서 주입
    dispatcher: SlashCommandDispatcher | None = field(default=None)
    # TUI 음성 컨트롤러 — _build_infra()에서 주입 (voice.tui_enabled일 때만)
    voice_controller: Any = field(default=None)


# ── 팩토리 헬퍼 ───────────────────────────────────────────────────────────────


def _build_infra(settings: JarvisSettings) -> tuple[AppContext, dict[str, Any]]:
    """공통 인프라를 생성하고 (AppContext, extra)를 반환."""
    from jarvis.agent_layer.memory.chain import MemoryMiddlewareChain
    from jarvis.agent_layer.memory.compaction import CompactionMiddleware
    from jarvis.agent_layer.memory.long_term import LongTermMemory
    from jarvis.agent_layer.memory.short_term import ShortTermMemory
    from jarvis.core.plugins.loader import PluginLoader
    from jarvis.core.plugins.runner import PluginRunner
    from jarvis.core.policy.authenticator import NoAuthAuthenticator
    from jarvis.core.policy.pipeline import SecurityPipeline
    from jarvis.core.policy.policy import AllowAllPolicy
    from jarvis.core.policy.sandbox import DefaultSandbox
    from jarvis.core.policy.validator import DefaultInputValidator
    from jarvis.core.skills.registry import SkillRegistry
    from jarvis.core.tools.builtin.bash import BashTool
    from jarvis.core.tools.builtin.edit_file import EditFileTool
    from jarvis.core.tools.builtin.glob import GlobTool
    from jarvis.core.tools.builtin.grep import GrepTool
    from jarvis.core.tools.builtin.list_dir import ListDirTool
    from jarvis.core.tools.builtin.read_file import ReadFileTool
    from jarvis.core.tools.builtin.web_fetch import WebFetchTool
    from jarvis.core.tools.builtin.web_search import WebSearchTool
    from jarvis.core.tools.builtin.write_file import WriteFileTool
    from jarvis.core.tools.loader import ToolLoader
    from jarvis.core.tools.registry import ToolRegistry

    tool_registry = ToolRegistry()
    tool_registry.register(BashTool())
    tool_registry.register(ReadFileTool())
    tool_registry.register(WriteFileTool())
    tool_registry.register(EditFileTool())
    tool_registry.register(GlobTool())
    tool_registry.register(GrepTool())
    tool_registry.register(ListDirTool())
    tool_registry.register(WebSearchTool())
    tool_registry.register(WebFetchTool())

    from jarvis.model_layer.types import ModelConfig
    model_config = ModelConfig(
        provider=settings.llm.provider,
        model=settings.llm.model,
        api_key=settings.llm.api_key.get_secret_value() if settings.llm.api_key else None,
        base_url=settings.llm.base_url,
        temperature=settings.llm.temperature,
        max_tokens=settings.llm.max_tokens,
    )

    if settings.memory.backend == "in_memory":
        from jarvis.agent_layer.memory.backends.in_memory_ltm import InMemoryLTMBackend
        from jarvis.agent_layer.memory.backends.in_memory_stm import InMemorySTMBackend
        stm_backend = InMemorySTMBackend()
        ltm_backend = InMemoryLTMBackend()
    else:
        dsn = settings.memory.postgres_dsn or settings.session.postgres_dsn
        if not dsn:
            raise ValueError(
                "JARVIS_MEMORY__POSTGRES_DSN 또는 JARVIS_SESSION__POSTGRES_DSN 설정 필요"
            )
        from jarvis.agent_layer.memory.backends.postgres_ltm import PostgresLTMBackend
        from jarvis.agent_layer.memory.backends.postgres_stm import PostgresSTMBackend
        stm_backend = PostgresSTMBackend(dsn=dsn)
        ltm_backend = PostgresLTMBackend(dsn=dsn)

    memory_chain = MemoryMiddlewareChain(stages=[
        ShortTermMemory(stm_backend),
        CompactionMiddleware(
            model=model_config,
            threshold_chars=settings.memory.compaction_threshold,
            ltm_backend=ltm_backend,
        ),
        LongTermMemory(ltm_backend),
    ])

    if settings.session.persistence_backend == "postgres":
        from jarvis.agent_layer.session.postgres import PostgresSessionRepo
        if not settings.session.postgres_dsn:
            raise ValueError(
                "JARVIS_SESSION__POSTGRES_DSN must be set when persistence_backend=postgres"
            )
        session_repo = PostgresSessionRepo(dsn=settings.session.postgres_dsn)
    else:
        from jarvis.agent_layer.session.jsonl import JsonlSessionRepo
        session_repo = JsonlSessionRepo(sessions_root=settings.session.sessions_dir)

    sandbox = DefaultSandbox(
        dangerous_patterns=settings.security.dangerous_commands,
        require_approval_for=settings.security.require_approval_for,
    )
    pipeline = SecurityPipeline(
        validator=DefaultInputValidator(max_length=settings.security.input_max_length),
        authenticator=NoAuthAuthenticator(),
        policy=AllowAllPolicy(),
        sandbox=sandbox,
    )

    skill_registry = SkillRegistry()
    plugin_runner = PluginRunner()

    # _async_setup() 에서 수집된 에이전트 정의 — 클로저로 공유
    _agent_defs: list[Any] = []

    async def _async_setup() -> None:
        nonlocal _agent_defs
        # 개발 중 고정 세션 유지. 추후 UUID 방식으로 교체 예정.
        await session_repo.create(session_id="default")

        tools_dir = Path(settings.plugin.tools_dir).expanduser()
        if tools_dir.exists():
            loader = ToolLoader(tool_registry)
            await loader.load_directory(str(tools_dir))

        skills_dir = Path(settings.plugin.skills_dir).expanduser()
        if skills_dir.exists():
            await skill_registry.load_directory(str(skills_dir))

        plugins_dir = Path(settings.plugin.plugins_dir).expanduser()
        if plugins_dir.exists():
            plugin_loader = PluginLoader(plugin_runner)
            await plugin_loader.load_directory(str(plugins_dir))

        if settings.mcp_servers:
            from jarvis.core.tools.mcp_loader import MCPToolLoader
            mcp_loader = MCPToolLoader(tool_registry)
            await mcp_loader.load_servers(settings.mcp_servers)

        # 에이전트 정의 로딩 + 서브 세션 사전 생성
        if settings.agents.enabled:
            from jarvis.core.multi_agent.loader import load_agent_definitions
            _agent_defs = load_agent_definitions(settings.agents.agents_dir)
            for defn in _agent_defs:
                await session_repo.create(session_id=f"agent_{defn.name}")

    asyncio.run(_async_setup())

    # Scheduler 초기화 (croniter 없으면 graceful skip은 service._loop()에서 처리)
    scheduler = None
    if settings.scheduler.enabled:
        from jarvis.core.scheduler.loader import load_tasks
        from jarvis.core.scheduler.service import SchedulerService
        sched_tasks = load_tasks(settings.scheduler.schedules_dir)
        scheduler = SchedulerService(
            tasks=sched_tasks,
            session_repo=session_repo,
            tool_registry=tool_registry,
            model=model_config,
            base_extra={},  # filled in after extra dict is built below
        )

    ctx = AppContext(
        session_repo=session_repo,
        tool_registry=tool_registry,
        settings=settings,
    )

    _extra: dict[str, Any] = {
        "memory_chain": memory_chain,
        "pipeline": pipeline,
        "plugin_runner": plugin_runner,
        "skill_registry": skill_registry,
        "sandbox": sandbox,  # approval_callback 나중에 주입용
        "stm_backend": stm_backend,
        "ltm_backend": ltm_backend,
        "model_config": model_config,
    }

    # Scheduler의 base_extra를 채워 넣는다 (extra가 만들어진 이후)
    if scheduler is not None:
        scheduler._base_extra = _extra
        ctx.scheduler = scheduler

    # YAML 에이전트 정의 → AgentNodeTool 등록 (extra 완성 후)
    if settings.agents.enabled and _agent_defs:
        for defn in _agent_defs:
            try:
                tool = _build_agent_node(defn, ctx, tool_registry, _extra)
                tool_registry.register(tool)
                print(f"[AgentLoader] Loaded agent: {defn.name} (tool: {tool.name})")
            except Exception as exc:
                print(f"[AgentLoader] Failed to load agent '{defn.name}': {exc}")

    # SlashCommandDispatcher 생성 (scheduler + LTM 연결)
    from jarvis.core.slash.dispatcher import SlashCommandDispatcher
    from jarvis.core.slash.remember_cmd import make_remember_handler

    ctx.dispatcher = SlashCommandDispatcher(scheduler=ctx.scheduler)
    ctx.dispatcher.register(
        "remember",
        make_remember_handler(ltm_backend),
        "내용 저장/검색/삭제 (list | search <키워드> | forget <id>)",
    )

    # 운영용 슬래시 커맨드
    from jarvis.core.slash.ops_cmd import (
        make_branch_handler,
        make_compact_handler,
        make_sessions_handler,
        make_tools_handler,
    )

    ctx.dispatcher.register(
        "sessions", make_sessions_handler(session_repo), "저장된 세션 목록 표시"
    )
    ctx.dispatcher.register(
        "branch", make_branch_handler(session_repo), "[session_id] 세션을 분기"
    )
    ctx.dispatcher.register(
        "tools", make_tools_handler(tool_registry), "사용 가능한 도구 목록 표시"
    )
    ctx.dispatcher.register(
        "compact",
        make_compact_handler(model_config, session_repo, ltm_backend),
        "현재 세션을 요약해 장기 기억에 저장",
    )

    from jarvis.core.slash.cost_cmd import make_cost_handler
    from jarvis.core.slash.export_cmd import make_export_handler

    ctx.dispatcher.register(
        "export", make_export_handler(session_repo), "현재 세션 대화 내보내기 (md | json)"
    )
    ctx.dispatcher.register(
        "cost", make_cost_handler(session_repo), "현재 세션 토큰 사용량·추정 비용 리포트"
    )

    # TUI 음성 컨트롤러 (voice.tui_enabled일 때만; 프로바이더 import 실패 시 graceful skip)
    if settings.voice.tui_enabled:
        try:
            from jarvis.ui.tui.voice import TuiVoiceController
            from jarvis.voice.service import VoiceService

            voice_service = VoiceService.from_config(
                stt_provider=settings.voice.stt_provider,
                tts_provider=settings.voice.tts_provider,
            )
            ctx.voice_controller = TuiVoiceController(voice_service)
        except Exception as exc:
            print(f"[Voice] TUI 음성 비활성화 (초기화 실패): {exc}")

    return ctx, _extra


def _build_agent_session(session_id: str, ctx: AppContext, extra: dict[str, Any]) -> AgentSession:
    """주어진 session_id로 AgentSession을 생성한다."""
    from jarvis.core.session import AgentSession
    from jarvis.model_layer.types import ModelConfig

    settings = ctx.settings
    model = ModelConfig(
        provider=settings.llm.provider,
        model=settings.llm.model,
        api_key=settings.llm.api_key.get_secret_value() if settings.llm.api_key else None,
        base_url=settings.llm.base_url,
        temperature=settings.llm.temperature,
        max_tokens=settings.llm.max_tokens,
    )
    thought_engine, thought_log, thought_composer = _build_thought(ctx, extra, model)

    return AgentSession(
        model=model,
        session_id=session_id,
        security_pipeline=extra["pipeline"],
        plugin_runner=extra["plugin_runner"],
        memory_chain=extra["memory_chain"],
        tool_registry=ctx.tool_registry,
        skill_registry=extra["skill_registry"],
        session_repo=ctx.session_repo,
        thought_engine=thought_engine,
        thought_log=thought_log,
        thought_composer=thought_composer,
        proactivity_factory=_build_proactivity_factory(ctx),
    )


def _build_proactivity_factory(ctx: AppContext) -> Any:
    """ProactiveConfig.enabled일 때만 ProactivityCore 팩토리를 만든다.

    코어는 세션별 emit에 바인딩돼야 하므로 (emit) -> ProactivityCore 팩토리를 반환.
    비활성(기본)이면 None — session은 Dual-Channel 분기를 건너뛴다.
    """
    pcfg = ctx.settings.proactive
    # 사고가 꺼져 있으면 프레임이 없어 proactivity가 무의미 → 함께 off.
    if not pcfg.enabled or not ctx.settings.thought.enabled:
        return None

    from jarvis.core.proactive import DefaultProactivityCore, DefaultProactivityPolicy

    def factory(emit: Any) -> Any:
        policy = DefaultProactivityPolicy(
            confidence_threshold=pcfg.confidence_threshold,
            cooldown_sec=pcfg.cooldown_sec,
        )
        return DefaultProactivityCore(emit_proactive=emit, policy=policy)

    return factory


def _build_thought(
    ctx: AppContext, extra: dict[str, Any], main_model: Any
) -> tuple[Any, Any, Any]:
    """ThoughtConfig.enabled일 때만 (엔진, 로그, composer)를 만든다.

    비활성(기본)이면 (None, None, None) — session은 사고 분기를 건너뛴다.
    - A1: provider/api_key/base_url까지 분리한 사고 모델
    - A2: log_sinks(ltm|stm) 선택 → ThoughtLog fan-out
    - A3: composer(default|interpretation_only) 선택
    """
    settings = ctx.settings
    if not settings.thought.enabled:
        return None, None, None

    from jarvis.agent_layer.thought import (
        DefaultThoughtComposer,
        InnerThoughtEngine,
        InterpretationOnlyComposer,
        LTMThoughtSink,
        STMThoughtSink,
        ThoughtLog,
        ThoughtPromptTemplate,
    )
    from jarvis.agent_layer.thought.prompt import DEFAULT_REFLECTION_TEMPLATE
    from jarvis.model_layer.types import ModelConfig

    tcfg = settings.thought

    # A1 — 사고 모델: 지정된 항목만 메인에서 분리, 비우면 메인 값 상속.
    api_key = (
        tcfg.api_key.get_secret_value() if tcfg.api_key is not None else main_model.api_key
    )
    thought_model = ModelConfig(
        provider=tcfg.provider or main_model.provider,
        model=tcfg.model or main_model.model,
        api_key=api_key,
        base_url=tcfg.base_url or main_model.base_url,
        temperature=main_model.temperature,
        max_tokens=main_model.max_tokens,
    )

    engine = InnerThoughtEngine(
        model=thought_model,
        template=ThoughtPromptTemplate.load(tcfg.prompt_path),
        reflection_template=ThoughtPromptTemplate.load(
            tcfg.reflection_prompt_path, default=DEFAULT_REFLECTION_TEMPLATE
        ),
        recall=extra["memory_chain"].retrieve,
        recall_limit=tcfg.recall_limit,
        skip_if_shorter_than=tcfg.skip_if_shorter_than,
    )

    # A2 — 사고 로그 싱크: 설정된 것만, 알 수 없는 이름은 무시.
    sink_factories = {
        "ltm": lambda: LTMThoughtSink(extra["ltm_backend"]),
        "stm": lambda: STMThoughtSink(extra["stm_backend"]),
    }
    sinks = [sink_factories[name]() for name in tcfg.log_sinks if name in sink_factories]
    log = ThoughtLog(sinks)

    # A3 — 조립 전략.
    composers = {
        "default": DefaultThoughtComposer,
        "interpretation_only": InterpretationOnlyComposer,
    }
    composer = composers.get(tcfg.composer, DefaultThoughtComposer)()

    return engine, log, composer


def _build_agent_node(
    defn: Any,
    ctx: AppContext,
    main_registry: Any,
    extra: dict[str, Any],
) -> Any:
    """AgentDefinition → 격리된 AgentSession → AgentNode → AgentNodeTool.

    각 에이전트는 독립된 AgentSession을 가진다:
    - system_prompt: 에이전트 전용 역할 지시
    - tool subset: defn.tools 목록만 허용 (빈 경우 전체 상속)
    - model: defn.model_override 지정 가능 (None이면 메인 모델 상속)
    """
    from jarvis.core.multi_agent.factory import AgentFactory
    from jarvis.core.multi_agent.tool import AgentNodeTool
    from jarvis.core.session import AgentSession
    from jarvis.core.tools.registry import ToolRegistry
    from jarvis.model_layer.types import ModelConfig

    settings = ctx.settings
    model_config: ModelConfig = extra["model_config"]

    # 모델 오버라이드
    if defn.model_override:
        model = ModelConfig(
            provider=settings.llm.provider,
            model=defn.model_override,
            api_key=settings.llm.api_key.get_secret_value() if settings.llm.api_key else None,
            base_url=settings.llm.base_url,
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens,
        )
    else:
        model = model_config

    # 도구 서브셋 (미지정이면 메인 레지스트리 전체 공유)
    if defn.tools:
        agent_registry = ToolRegistry()
        for tool_name in defn.tools:
            t = main_registry.get(tool_name)
            if t is not None:
                agent_registry.register(t)
    else:
        agent_registry = main_registry

    session = AgentSession(
        model=model,
        session_id=f"agent_{defn.name}",
        security_pipeline=extra["pipeline"],
        plugin_runner=extra["plugin_runner"],
        memory_chain=extra["memory_chain"],
        tool_registry=agent_registry,
        skill_registry=extra["skill_registry"],
        session_repo=ctx.session_repo,
        system_prompt=defn.system_prompt,
        agent_name=defn.name,
    )

    factory = AgentFactory()
    node = factory.create(defn, session)
    tool = AgentNodeTool(node)
    # AgentDefinition.description을 LLM이 읽는 툴 설명으로 사용
    if defn.description:
        tool.description = defn.description
    return tool


def build_session(
    plan: TUIPlan | SessionResumePlan,
    ctx: AppContext,
    extra: dict[str, Any],
) -> AgentSession:
    session_id = getattr(plan, "session_id", None) or "default"
    return _build_agent_session(session_id, ctx, extra)


def make_branch_factory(
    ctx: AppContext,
    extra: dict[str, Any],
) -> Callable[[str], Awaitable[AgentSession]]:
    """
    Ctrl+F용 브랜치 팩토리.
    parent_session_id를 받아 메시지를 복사한 새 AgentSession을 반환한다.
    """

    async def _factory(parent_session_id: str) -> AgentSession:
        repo = ctx.session_repo
        if hasattr(repo, "create_branch"):
            meta = await repo.create_branch(parent_session_id)
        else:
            import uuid as _uuid
            meta = await repo.create(session_id=str(_uuid.uuid4()))
        return _build_agent_session(meta.session_id, ctx, extra)

    return _factory


def make_session_factory(
    ctx: AppContext,
    extra: dict[str, Any],
) -> Callable[[], Awaitable[AgentSession]]:
    """
    Ctrl+N용 새 UUID 세션 팩토리를 반환한다.
    반환된 callable은 async — TUI on_mount 이후에만 호출할 것.
    """

    async def _factory() -> AgentSession:
        new_id = str(uuid.uuid4())
        await ctx.session_repo.create(session_id=new_id)
        return _build_agent_session(new_id, ctx, extra)

    return _factory


# ── main() 진입점 ─────────────────────────────────────────────────────────────


def main() -> None:
    from jarvis.config import get_settings

    plan = parse_startup_plan()

    if plan.kind == "help":
        print(
            "Usage: jarvis [OPTIONS]\n\n"
            "Options:\n"
            "  -s, --session ID       기존 세션 재개\n"
            "  --list-sessions        저장된 세션 목록 출력\n"
            "  --web                  Web HUD 모드 실행\n"
            "  --host HOST            Web 서버 호스트 (기본: 127.0.0.1)\n"
            "  --port PORT            Web 서버 포트 (기본: 7777)\n"
            "  -v, --version          버전 출력\n"
            "  -h, --help             이 도움말 출력\n"
        )
        return

    if plan.kind == "version":
        print("jarvis 0.1.0")
        return

    settings = get_settings()
    ctx, extra = _build_infra(settings)

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

    # WebPlan → Web HUD 실행
    if plan.kind == "web":
        from jarvis.ui.web.startup import run_web
        session_id = plan.session_id or "default"
        run_web(ctx=ctx, extra=extra, session_id=session_id, host=plan.host, port=plan.port)
        return

    # TUIPlan or SessionResumePlan → TUI 실행
    from jarvis.ui.tui.app import JarvisTUI

    ctx.session_factory = make_session_factory(ctx, extra)
    ctx.branch_factory = make_branch_factory(ctx, extra)
    session = build_session(plan, ctx, extra)
    app = JarvisTUI(session=session, ctx=ctx)

    # ApprovalDialog를 sandbox의 approval_callback으로 연결
    extra["sandbox"].set_approval_callback(app.request_approval)

    app.run()

    # TUI 종료 후 세션 요약을 LTM에 저장
    async def _on_session_end() -> None:
        stm = extra.get("stm_backend")
        ltm = extra.get("ltm_backend")
        model = extra.get("model_config")
        if stm is None or ltm is None or model is None:
            return
        try:
            msgs = await stm.load(session._session_id)
            if not msgs:
                return
            from jarvis.agent_layer.memory.episodic import EpisodicSummarizer
            summarizer = EpisodicSummarizer(model=model, ltm_backend=ltm)
            entry_id = await summarizer.save_session(session._session_id, msgs)
            if entry_id:
                print(f"[Episodic] Session summary saved (id: {entry_id[:8]})")
        except Exception as exc:
            print(f"[Episodic] Session summary failed (non-fatal): {exc}")

    asyncio.run(_on_session_end())
