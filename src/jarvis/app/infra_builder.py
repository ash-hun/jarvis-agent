"""[app] InfraBuilder: 설정 하나로 도구, 메모리, 저장소, 보안, 스케줄러, proactive, 슬래시 명령을 조립한다."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import SecretStr

from jarvis.app.agent_profile import MAIN_AGENT_ID, AgentProfile
from jarvis.app.agent_registry import AgentRegistry
from jarvis.app.app_assembly import AppAssembly
from jarvis.app.app_context import AppContext
from jarvis.app.app_services import AppServices
from jarvis.app.subagent_builder import SubagentBuilder
from jarvis.common.logger import get_logger

if TYPE_CHECKING:
    from jarvis.agent_layer.openloop.store import OpenLoopStore
    from jarvis.agent_layer.session.protocol import SessionRepo
    from jarvis.agent_layer.usermodel.store import UserModelStore
    from jarvis.config import JarvisSettings
    from jarvis.core.external import ExternalEventInbox, ExternalEventPoller
    from jarvis.core.multi_agent.factory import AgentDefinition
    from jarvis.core.multi_agent.service import OrchestrationService
    from jarvis.core.notify import Notify
    from jarvis.core.plugins.runner import PluginRunner
    from jarvis.core.proactive.triggers import ActivityClock, ExternalTrigger, ReflectionTrigger
    from jarvis.core.procedures.learner import ProcedureLearner
    from jarvis.core.procedures.store import ProcedureStore
    from jarvis.core.scheduler.service import SchedulerService
    from jarvis.core.skills.registry import SkillRegistry
    from jarvis.core.tools.registry import ToolRegistry
    from jarvis.memory.memory_service import MemoryService
    from jarvis.model_layer.types import ModelConfig

logger = get_logger(__name__)

ExternalParts = tuple["ExternalEventInbox | None", "ExternalEventPoller | None", "ExternalTrigger | None"]


class InfraBuilder:
    """build() 한 번이 앱 전체를 조립한다. 각 build_* 는 기능 하나를 맡고 테스트에서 따로 부를 수 있다."""

    def __init__(self, settings: "JarvisSettings") -> None:
        self._settings = settings

    def build(self) -> AppAssembly:
        """기동 순서: 도구, 모델, 메모리, 세션 저장소, 보안, 절차, 확장, 스케줄러, 앱 상태, 에이전트, 명령."""
        settings = self._settings
        tool_registry = self.build_tool_registry()
        model_config = self.build_model_config()
        from jarvis.core.skills.registry import SkillRegistry

        # 스킬 레지스트리는 절차 기억(읽기 전용)으로 노출되므로 메모리보다 먼저 만든다
        skill_registry = SkillRegistry()
        memory = self.build_memory(model_config, skill_registry)
        from jarvis.core.tools.task_pattern import TaskPatternTool

        # 작업 패턴 저장은 메모리가 있어야 해서 메모리 다음에 등록한다. 모든 에이전트가 쓴다
        tool_registry.register(TaskPatternTool(memory))
        from jarvis.agent_layer.memory.chain import MemoryMiddlewareChain
        from jarvis.agent_layer.memory.memory_adapter import MemoryMiddlewareAdapter

        # 메모리 모듈은 서비스 하나. harness 의 미들웨어 체인에는 어댑터 한 단계로 꽂힌다
        memory_chain = MemoryMiddlewareChain(stages=[MemoryMiddlewareAdapter(memory)])
        session_repo = self.build_session_repo()

        from jarvis.core.policy.approval_rules import ApprovalRules
        from jarvis.core.policy.authenticator import NoAuthAuthenticator
        from jarvis.core.policy.pipeline import SecurityPipeline
        from jarvis.core.policy.policy import AllowAllPolicy
        from jarvis.core.policy.sandbox import DefaultSandbox
        from jarvis.core.policy.validator import DefaultInputValidator

        # 승인 기억은 앱에 하나. web 의 세션별 sandbox 도 같은 규칙 파일을 본다
        approval_rules = ApprovalRules(settings.security.approvals_path)
        sandbox = DefaultSandbox(
            dangerous_patterns=settings.security.dangerous_commands,
            require_approval_for=settings.security.require_approval_for,
            approval_rules=approval_rules,
        )
        pipeline = SecurityPipeline(
            validator=DefaultInputValidator(max_length=settings.security.input_max_length),
            authenticator=NoAuthAuthenticator(),
            policy=AllowAllPolicy(),
            sandbox=sandbox,
        )
        from jarvis.core.plugins.runner import PluginRunner

        plugin_runner = PluginRunner()
        procedure_store, procedure_learner = self.build_procedures(model_config)
        agent_defs = asyncio.run(
            self.load_extensions(session_repo, tool_registry, skill_registry, plugin_runner, procedure_store)
        )
        scheduler = self.build_scheduler(session_repo, tool_registry, model_config, plugin_runner, skill_registry)

        ctx = AppContext(
            session_repo=session_repo,
            tool_registry=tool_registry,
            settings=settings,
            agent_tools=self.build_agent_tools(),
        )
        # open loop 과 사용자 모델 저장소는 앱에 하나(모든 세션과 daemon 이 공유)
        openloop_store = self.build_openloop_store() if settings.thought.enabled else None
        user_model_store = (
            self.build_user_model_store() if settings.thought.enabled and settings.user_model.enabled else None
        )
        from jarvis.core.proactive import ActivityClock, FeedbackLearner

        # 외부 이벤트 소스는 트리거 합성보다 먼저 만든다
        external_inbox, external_poller, external_trigger = self.build_external()
        activity_clock = ActivityClock()
        feedback_learner = FeedbackLearner(base_threshold=settings.proactive.confidence_threshold)
        ctx.activity_clock = activity_clock
        ctx.reflection_trigger = self.build_reflection_trigger(activity_clock, external_trigger)
        ctx.feedback_learner = feedback_learner
        ctx.external_inbox = external_inbox
        ctx.external_poller = external_poller
        ctx.memory = memory
        ctx.notifier = self.build_notifier()
        ctx.procedure_learner = procedure_learner
        # TUI 모드엔 화면 방송이 없다. 외부 채널이 있으면 스케줄 결과가 거기로 간다(web 은 기동 시 fan_out 으로 덮는다)
        if scheduler is not None and ctx.notifier is not None:
            scheduler.set_notifier(ctx.notifier)
        ctx.scheduler = scheduler

        services = AppServices(
            memory_chain=memory_chain,
            pipeline=pipeline,
            plugin_runner=plugin_runner,
            skill_registry=skill_registry,
            sandbox=sandbox,
            approval_rules=approval_rules,
            memory=memory,
            model_config=model_config,
            activity_clock=activity_clock,
            procedure_learner=procedure_learner,
            openloop_store=openloop_store,
            user_model_store=user_model_store,
            external_inbox=external_inbox,
        )
        orchestration = self.build_subagents(ctx, services, agent_defs)
        self.register_commands(ctx, services, procedure_store, agent_defs, orchestration)
        profile = AgentProfile.main(settings, model_config, feedback_learner)
        agents = AgentRegistry.load(ctx, services, profile, settings.team.dir)
        # 에이전트가 둘 이상이면 서로 묻는 도구. 받는 쪽 세션은 기본으로 레지스트리가 열고 Web 이 기동 때 바꾼다
        if len(agents.ids()) > 1:
            from jarvis.app.agent_conversation import AskAgentTool

            tool_registry.register(AskAgentTool(agents, agents.open_peer_session))
        if scheduler is not None:
            scheduler.set_agent_resolver(agents.task_agent)
        return AppAssembly(
            ctx=ctx, services=services, profile=profile, sessions=agents.builder(MAIN_AGENT_ID), agents=agents
        )

    def build_tool_registry(self) -> "ToolRegistry":
        from jarvis.core.tools.builtin.bash import BashTool
        from jarvis.core.tools.builtin.edit_file import EditFileTool
        from jarvis.core.tools.builtin.glob import GlobTool
        from jarvis.core.tools.builtin.grep import GrepTool
        from jarvis.core.tools.builtin.list_dir import ListDirTool
        from jarvis.core.tools.builtin.read_file import ReadFileTool
        from jarvis.core.tools.builtin.web_fetch import WebFetchTool
        from jarvis.core.tools.builtin.web_search import WebSearchTool
        from jarvis.core.tools.builtin.write_file import WriteFileTool
        from jarvis.core.tools.registry import ToolRegistry

        registry = ToolRegistry()
        for tool in (
            BashTool(), ReadFileTool(), WriteFileTool(), EditFileTool(), GlobTool(), GrepTool(),
            ListDirTool(), WebSearchTool(), WebFetchTool(),
        ):
            registry.register(tool)
        return registry

    def build_agent_tools(self) -> "ToolRegistry":
        """에이전트 정의가 이름으로 골라야 쓰는 도구. JARVIS(도구 목록 없음)의 레지스트리에는 넣지 않는다."""
        from jarvis.core.tools.housing import housing_tools
        from jarvis.core.tools.registry import ToolRegistry

        registry = ToolRegistry()
        for tool in housing_tools():
            registry.register(tool)
        return registry

    def build_model_config(self) -> "ModelConfig":
        from jarvis.model_layer.types import ModelConfig

        llm = self._settings.llm
        return ModelConfig(
            provider=llm.provider,
            model=llm.model,
            api_key=llm.api_key.get_secret_value() if llm.api_key else None,
            base_url=llm.base_url,
            temperature=llm.temperature,
            max_tokens=llm.max_tokens,
        )

    def build_memory(self, model_config: "ModelConfig", skill_registry: "SkillRegistry") -> "MemoryService":
        """임베딩, 항목과 작업 기억 저장소(in_memory 또는 Postgres), 요약과 사실 추출을 단 메모리 서비스."""
        from jarvis.memory.consolidation import llm_summarizer
        from jarvis.memory.consolidation.semantic_extract import llm_fact_extractor
        from jarvis.memory.long_term.procedural import SkillRegistryProcedures
        from jarvis.memory.memory_service import MemoryService
        from jarvis.memory.retrieval import ScoringParams
        from jarvis.model_layer.embeddings import build_embedder

        settings = self._settings
        mcfg = settings.memory
        embedder = build_embedder(
            mcfg.embedding_provider,
            model=mcfg.embedding_model,
            dimensions=mcfg.embedding_dimensions,
            api_key=(mcfg.embedding_api_key or settings.llm.api_key or SecretStr("")).get_secret_value() or None,
            base_url=mcfg.embedding_base_url,
        )
        from jarvis.memory.stores.protocol import ItemStore
        from jarvis.memory.working.state import WorkingStore

        item_store: ItemStore
        working_store: WorkingStore
        if mcfg.backend == "in_memory":
            from jarvis.memory.stores.in_memory import InMemoryItemStore
            from jarvis.memory.working.in_memory import InMemoryWorkingStore

            item_store = InMemoryItemStore()
            working_store = InMemoryWorkingStore()
        else:
            dsn = mcfg.postgres_dsn or settings.session.postgres_dsn
            if not dsn:
                raise ValueError("JARVIS_MEMORY__POSTGRES_DSN 또는 JARVIS_SESSION__POSTGRES_DSN 설정 필요")
            from jarvis.memory.stores.postgres import PostgresItemStore
            from jarvis.memory.working.postgres import PostgresWorkingStore

            item_store = PostgresItemStore(dsn=dsn, dimensions=embedder.dimensions if embedder else 0)
            working_store = PostgresWorkingStore(dsn=dsn)

        return MemoryService(
            item_store,
            working_store,
            summarizer=llm_summarizer(model_config),
            extractor=llm_fact_extractor(model_config),
            procedures=SkillRegistryProcedures(skill_registry),
            threshold_chars=mcfg.compaction_threshold,
            window_size=mcfg.window_size,
            inject_limit=mcfg.recall_limit,
            fixed_facts=mcfg.fixed_facts,
            importance_threshold=mcfg.importance_threshold,
            scoring=ScoringParams(
                recency_half_life_hours=mcfg.recency_half_life_hours,
                importance_half_life_hours=mcfg.importance_half_life_days * 24,
            ),
            interference_threshold=mcfg.interference_threshold,
            embedder=embedder,
            min_similarity=mcfg.min_similarity,
        )

    def build_session_repo(self) -> "SessionRepo":
        scfg = self._settings.session
        if scfg.persistence_backend == "postgres":
            from jarvis.agent_layer.session.postgres import PostgresSessionRepo

            if not scfg.postgres_dsn:
                raise ValueError("JARVIS_SESSION__POSTGRES_DSN must be set when persistence_backend=postgres")
            return PostgresSessionRepo(dsn=scfg.postgres_dsn)
        from jarvis.agent_layer.session.jsonl import JsonlSessionRepo

        return JsonlSessionRepo(sessions_root=scfg.sessions_dir)

    def build_procedures(self, model_config: "ModelConfig") -> tuple["ProcedureStore", "ProcedureLearner | None"]:
        from jarvis.core.procedures import ProcedureLearner, ProcedureStore, llm_distiller

        pcfg = self._settings.procedures
        store = ProcedureStore(pcfg.dir)
        learner = (
            ProcedureLearner(store, llm_distiller(model_config), min_tool_calls=pcfg.min_tool_calls)
            if pcfg.enabled
            else None
        )
        return store, learner

    async def load_extensions(
        self,
        session_repo: "SessionRepo",
        tool_registry: "ToolRegistry",
        skill_registry: "SkillRegistry",
        plugin_runner: "PluginRunner",
        procedure_store: "ProcedureStore",
    ) -> list["AgentDefinition"]:
        """기본 세션, 사용자 도구, 스킬, 승인된 절차, 플러그인, MCP 를 싣고 서브 에이전트 정의를 돌려준다."""
        settings = self._settings
        # 개발 중 고정 세션 유지. 추후 UUID 방식으로 교체 예정
        await session_repo.create(session_id="default")

        tools_dir = Path(settings.plugin.tools_dir).expanduser()
        if tools_dir.exists():
            from jarvis.core.tools.loader import ToolLoader

            await ToolLoader(tool_registry).load_directory(str(tools_dir))

        skills_dir = Path(settings.plugin.skills_dir).expanduser()
        if skills_dir.exists():
            await skill_registry.load_directory(str(skills_dir))

        # 승인된 절차 → procedure_<name> 도구 + /<name> 스킬. 저장소가 비어 있으면 아무것도 안 한다
        if settings.procedures.enabled:
            from jarvis.core.procedures import register_approved

            names = register_approved(procedure_store, tool_registry, skill_registry)
            if names:
                logger.info(f"[Procedures] {len(names)} approved procedure(s) registered as tools")

        plugins_dir = Path(settings.plugin.plugins_dir).expanduser()
        if plugins_dir.exists():
            from jarvis.core.plugins.loader import PluginLoader

            await PluginLoader(plugin_runner).load_directory(str(plugins_dir))

        if settings.mcp_servers:
            from jarvis.core.tools.mcp_loader import MCPToolLoader

            await MCPToolLoader(tool_registry).load_servers(settings.mcp_servers)

        # 서브 세션은 첫 위임 때 부모 세션 기준으로 만든다(AgentFactory.node_for)
        if settings.agents.enabled:
            from jarvis.core.multi_agent.loader import load_agent_definitions

            return load_agent_definitions(settings.agents.agents_dir)
        return []

    def build_scheduler(
        self,
        session_repo: "SessionRepo",
        tool_registry: "ToolRegistry",
        model_config: "ModelConfig",
        plugin_runner: "PluginRunner",
        skill_registry: "SkillRegistry",
    ) -> "SchedulerService | None":
        """croniter 가 없으면 서비스의 루프가 조용히 건너뛴다."""
        scfg = self._settings.scheduler
        if not scfg.enabled:
            return None
        from jarvis.core.scheduler.loader import load_tasks
        from jarvis.core.scheduler.service import SchedulerService

        return SchedulerService(
            tasks=load_tasks(scfg.schedules_dir),
            session_repo=session_repo,
            tool_registry=tool_registry,
            model=model_config,
            schedules_dir=scfg.schedules_dir,
            plugin_runner=plugin_runner,
            skill_registry=skill_registry,
        )

    def build_openloop_store(self) -> "OpenLoopStore":
        """기본 jsonl. postgres 는 dsn 이 없으면 session/memory DSN 으로, 그래도 없으면 jsonl 로 물러선다."""
        settings = self._settings
        cfg = settings.openloop
        if cfg.backend == "in_memory":
            from jarvis.agent_layer.openloop import InMemoryOpenLoopStore

            return InMemoryOpenLoopStore()
        if cfg.backend == "postgres":
            dsn = cfg.postgres_dsn or settings.session.postgres_dsn or settings.memory.postgres_dsn
            if dsn:
                from jarvis.agent_layer.openloop import PostgresOpenLoopStore

                return PostgresOpenLoopStore(dsn=dsn)
        from jarvis.agent_layer.openloop import JsonlOpenLoopStore

        return JsonlOpenLoopStore(path=cfg.path)

    def build_user_model_store(self) -> "UserModelStore":
        cfg = self._settings.user_model
        if cfg.backend == "in_memory":
            from jarvis.agent_layer.usermodel import InMemoryUserModelStore

            return InMemoryUserModelStore()
        from jarvis.agent_layer.usermodel import JsonlUserModelStore

        return JsonlUserModelStore(path=cfg.path)

    def build_external(self) -> ExternalParts:
        """외부 이벤트 소스 → (inbox, poller, trigger). 꺼져 있거나 소스가 없으면 (None, None, None)."""
        settings = self._settings
        cfg = settings.external
        if not cfg.enabled:
            return None, None, None
        from jarvis.core.external import (
            ExternalEventInbox,
            ExternalEventPoller,
            InMemorySeenStore,
            JsonlSeenStore,
            SeenStore,
            build_mcp_sources,
            load_source_specs,
        )

        specs = load_source_specs(cfg.sources_dir)
        sources = build_mcp_sources(specs, settings.mcp_servers, detail_max_chars=cfg.detail_max_chars)
        if not sources:
            return None, None, None
        from jarvis.core.proactive import ExternalTrigger

        seen: SeenStore
        if cfg.seen_backend == "in_memory":
            seen = InMemorySeenStore(ttl_sec=cfg.seen_ttl_sec, max_keys=cfg.seen_max_keys)
        else:
            seen = JsonlSeenStore(path=cfg.seen_path, ttl_sec=cfg.seen_ttl_sec, max_keys=cfg.seen_max_keys)
        inbox = ExternalEventInbox(maxlen=cfg.inbox_max_events)
        trigger = ExternalTrigger()
        poller = ExternalEventPoller(
            sources,  # type: ignore[arg-type]  # McpToolSource 목록을 ExternalSource 목록으로 넘긴다(list 불변성)
            inbox,
            seen,
            trigger=trigger,
            max_events_per_tick=cfg.max_events_per_tick,
        )
        logger.info(f"[ExternalTrigger] {len(sources)} source(s) loaded from {cfg.sources_dir}")
        return inbox, poller, trigger

    def build_reflection_trigger(
        self, activity_clock: "ActivityClock", external_trigger: "ExternalTrigger | None" = None
    ) -> "ReflectionTrigger":
        """interval / idle / both. 외부 소스가 있으면 어떤 모드든 외부 트리거와 합성해 외부 이벤트로도 깬다."""
        from jarvis.core.proactive import AnyTrigger, IdleTrigger, IntervalTrigger

        pcfg = self._settings.proactive
        interval = IntervalTrigger(pcfg.daemon_interval_sec)
        idle = IdleTrigger(activity_clock, pcfg.daemon_idle_sec)
        base: ReflectionTrigger
        if pcfg.daemon_trigger == "idle":
            base = idle
        elif pcfg.daemon_trigger == "both":
            base = AnyTrigger([interval, idle])
        else:
            base = interval
        if external_trigger is None:
            return base
        return AnyTrigger([base, external_trigger])

    def build_notifier(self) -> "Notify | None":
        """채널 설정이 하나도 없으면 None(기존 동작 그대로)."""
        cfg = self._settings.notify
        if cfg.slack_webhook_url is None:
            return None
        from jarvis.core.notify import only_kinds, slack_notifier

        logger.info("[Notify] slack channel enabled")
        return only_kinds(cfg.kinds, slack_notifier(cfg.slack_webhook_url.get_secret_value()))

    def build_subagents(
        self, ctx: AppContext, services: AppServices, agent_defs: list["AgentDefinition"]
    ) -> "OrchestrationService | None":
        """정의마다 위임 도구를 등록하고, 하나라도 실리면 orchestrate 도구까지. 팩토리 하나를 모든 정의가 공유한다."""
        settings = self._settings
        if not settings.agents.enabled or not agent_defs:
            return None
        from jarvis.core.multi_agent.factory import AgentFactory
        from jarvis.core.multi_agent.orchestrate_tool import OrchestrateTool
        from jarvis.core.multi_agent.service import OrchestrationService, load_supervisor_prompt

        builder = SubagentBuilder(ctx, services, ctx.tool_registry)
        factory = AgentFactory(build_session=builder.build_session, session_repo=ctx.session_repo)
        loaded: list[AgentDefinition] = []
        for definition in agent_defs:
            try:
                tool = builder.node_tool(definition, factory)
                ctx.tool_registry.register(tool)
                loaded.append(definition)
                logger.info(f"[AgentLoader] Loaded agent: {definition.name} (tool: {tool.name})")
            except Exception as exc:
                logger.info(f"[AgentLoader] Failed to load agent '{definition.name}': {exc}")
        if not loaded:
            return None
        # 오케스트레이션: 메인 LLM 이 패턴을 고르는 도구. /orchestrate 는 명령 등록에서
        orchestration = OrchestrationService(
            loaded,
            factory,
            services.memory,
            supervisor_prompt=load_supervisor_prompt(settings.agents.supervisor_prompt),
        )
        ctx.tool_registry.register(OrchestrateTool(orchestration))
        logger.info(f"[AgentLoader] orchestrate tool ready ({len(loaded)} agent(s))")
        return orchestration

    def register_commands(
        self,
        ctx: AppContext,
        services: AppServices,
        procedure_store: "ProcedureStore",
        agent_defs: list["AgentDefinition"],
        orchestration: "OrchestrationService | None",
    ) -> None:
        """슬래시 명령 디스패처를 만들고, 켜진 기능의 명령만 등록한다."""
        from jarvis.core.scheduler.classify import make_llm_classifier
        from jarvis.core.slash.dispatcher import SlashCommandDispatcher
        from jarvis.core.slash.remember_cmd import make_remember_handler

        settings = self._settings
        model_config = services.model_config
        memory = services.memory
        session_repo = ctx.session_repo
        tool_registry = ctx.tool_registry
        # "/schedule ~에" 항목을 등록할 때 알림/작업을 한 번 가른다
        dispatcher = SlashCommandDispatcher(
            scheduler=ctx.scheduler,
            schedule_classifier=make_llm_classifier(model_config),
            skill_registry=services.skill_registry,
        )
        ctx.dispatcher = dispatcher
        dispatcher.register(
            "remember", make_remember_handler(memory), "내용 저장/검색/삭제 (list | search <키워드> | forget <id>)"
        )
        from jarvis.core.slash.patterns_cmd import make_patterns_handler

        dispatcher.register("patterns", make_patterns_handler(memory), "지금 에이전트의 작업 패턴 (forget <이름>)")
        if services.openloop_store is not None:
            from jarvis.core.slash.openloop_cmd import make_openloop_handler

            dispatcher.register(
                "openloop",
                make_openloop_handler(services.openloop_store),
                "추적 중인 약속/미완 작업 (done <id> | dismiss <id>)",
            )
        if services.user_model_store is not None:
            from jarvis.agent_layer.usermodel import UserModelBuilder
            from jarvis.core.slash.usermodel_cmd import make_usermodel_handler

            dispatcher.register(
                "usermodel",
                make_usermodel_handler(
                    services.user_model_store,
                    UserModelBuilder(model_config),
                    memory,
                    build_source_limit=settings.user_model.build_source_limit,
                ),
                "증류된 사용자 모델 (build로 갱신)",
            )
        if settings.thought.enabled:
            from jarvis.agent_layer.journal import ReflectionJournaler
            from jarvis.core.slash.journal_cmd import make_journal_handler

            dispatcher.register(
                "journal",
                make_journal_handler(ReflectionJournaler(model_config, memory)),
                "자기 성찰 저널 (write로 작성)",
            )

        from jarvis.core.slash.cleanup_cmd import make_cleanup_handler
        from jarvis.core.slash.cost_cmd import make_cost_handler
        from jarvis.core.slash.export_cmd import make_export_handler
        from jarvis.core.slash.ops_cmd import (
            make_branch_handler,
            make_compact_handler,
            make_sessions_handler,
            make_tools_handler,
        )
        from jarvis.core.slash.procedures_cmd import make_procedures_handler

        dispatcher.register("sessions", make_sessions_handler(session_repo), "저장된 세션 목록 표시")
        dispatcher.register("branch", make_branch_handler(session_repo), "[session_id] 세션을 분기")
        dispatcher.register("tools", make_tools_handler(tool_registry), "사용 가능한 도구 목록 표시")
        dispatcher.register(
            "procedures",
            make_procedures_handler(
                procedure_store,
                tool_registry,
                services.skill_registry,
                learner=services.procedure_learner,
                session_repo=session_repo,
            ),
            "학습된 절차 (approve <name> | reject <name> | show <name> | learn [session_id])",
        )
        dispatcher.register(
            "compact", make_compact_handler(model_config, session_repo, memory), "현재 세션을 요약해 장기 기억에 저장"
        )
        per_agent_sessions = {f"agent_{d.name}" for d in agent_defs if d.memory.stm == "per_agent"}
        dispatcher.register(
            "cleanup",
            make_cleanup_handler(session_repo, memory, keep_agent_sessions=per_agent_sessions),
            "옛 데이터 현황과 삭제 (agents | stm, confirm 필요)",
        )
        if orchestration is not None:
            from jarvis.core.slash.orchestrate_cmd import make_orchestrate_handler

            dispatcher.register(
                "orchestrate",
                make_orchestrate_handler(orchestration),
                "<pattern> [--agents a,b] [--promote] <작업>: 서브 에이전트들을 패턴으로 조율",
            )
        dispatcher.register("export", make_export_handler(session_repo), "현재 세션 대화 내보내기 (md | json)")
        dispatcher.register("cost", make_cost_handler(session_repo), "현재 세션 토큰 사용량·추정 비용 리포트")


def build_app(settings: "JarvisSettings") -> AppAssembly:
    """설정 하나로 앱 전체를 조립한다. TUI 와 Web 진입점이 부른다."""
    return InfraBuilder(settings).build()
