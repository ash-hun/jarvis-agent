"""[app] InfraBuilder: 설정 하나로 도구, 메모리, 저장소, 보안, 스케줄러, proactive, 슬래시 명령을 조립한다."""

import asyncio
from pathlib import Path
from pydantic import SecretStr
from typing import TYPE_CHECKING

from jarvis.app.agent_profile import MAIN_AGENT_ID, AgentProfile
from jarvis.app.subagent_builder import SubagentBuilder
from jarvis.app.agent_registry import AgentRegistry
from jarvis.app.app_assembly import AppAssembly
from jarvis.app.app_services import AppServices
from jarvis.app.app_context import AppContext
from jarvis.common.logger import get_logger

if TYPE_CHECKING:
    from jarvis.core.proactive.triggers import ActivityClock, ExternalTrigger, ReflectionTrigger
    from jarvis.core.external import ExternalEventInbox, ExternalEventPoller
    from jarvis.core.multi_agent.service import OrchestrationService
    from jarvis.agent_layer.usermodel.store import UserModelStore
    from jarvis.agent_layer.openloop.store import OpenLoopStore
    from jarvis.agent_layer.session.protocol import SessionRepo
    from jarvis.core.multi_agent.factory import AgentDefinition
    from jarvis.core.procedures.learner import ProcedureLearner
    from jarvis.core.scheduler.service import SchedulerService
    from jarvis.core.notify.discord_voice import DiscordVoice
    from jarvis.core.procedures.store import ProcedureStore
    from jarvis.memory.memory_service import MemoryService
    from jarvis.core.skills.registry import SkillRegistry
    from jarvis.core.plugins.runner import PluginRunner
    from jarvis.core.tools.registry import ToolRegistry
    from jarvis.model_layer.embeddings import Embedder
    from jarvis.core.notify.webpush import PushStore
    from jarvis.model_layer.types import ModelConfig
    from jarvis.config import JarvisSettings
    from jarvis.core.notify import Notify

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
        session_repo = self.build_session_repo()

        from jarvis.core.policy.authenticator import NoAuthAuthenticator
        from jarvis.core.policy.validator import DefaultInputValidator
        from jarvis.core.policy.approval_rules import ApprovalRules
        from jarvis.core.policy.pipeline import SecurityPipeline
        from jarvis.core.policy.sandbox import DefaultSandbox
        from jarvis.core.policy.policy import AllowAllPolicy

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
        if scheduler is not None:
            from jarvis.core.slash.schedule_cmd import make_schedule_handler
            from jarvis.core.scheduler.classify import make_llm_classifier
            from jarvis.core.scheduler.tool import ScheduleTool

            # 말로 "1분 뒤에 알려줘" 해도 /schedule 과 같은 일정이 생기게
            tool_registry.register(ScheduleTool(make_schedule_handler(scheduler, make_llm_classifier(model_config))))
            from jarvis.core.goals.runner import GoalRunner
            from jarvis.core.goals.store import GoalStore
            from jarvis.core.goals.tool import GoalTool

            # 맡긴 목표는 스케줄러가 차례를 돌린다. 도구와 러너가 같은 저장소를 본다
            goals = GoalStore()
            scheduler.set_goal_runner(GoalRunner(goals))
            tool_registry.register(GoalTool(goals, scheduler))

        # open loop 과 사용자 모델 저장소는 앱에 하나(모든 세션과 daemon 이 공유). 청약 도구도 약속을 남겨 먼저 만든다
        openloop_store = self.build_openloop_store() if settings.thought.enabled else None
        ctx = AppContext(
            session_repo=session_repo,
            tool_registry=tool_registry,
            settings=settings,
            agent_tools=self.build_agent_tools(memory, openloop_store),
        )
        user_model_store = (
            self.build_user_model_store() if settings.thought.enabled and settings.user_model.enabled else None
        )
        from jarvis.core.proactive import ActivityClock, FeedbackLearner

        # 외부 이벤트 소스는 트리거 합성보다 먼저 만든다
        external_inbox, external_poller, external_trigger = self.build_external()
        activity_clock = ActivityClock()
        feedback_learner = FeedbackLearner(base_threshold=settings.proactive.effective_threshold())
        ctx.activity_clock = activity_clock
        ctx.reflection_trigger = self.build_reflection_trigger(activity_clock, external_trigger)
        ctx.feedback_learner = feedback_learner
        ctx.external_inbox = external_inbox
        ctx.external_poller = external_poller
        ctx.memory = memory
        ctx.push_store = self.build_push_store()
        ctx.notifier = self.build_notifier(ctx.push_store)
        ctx.procedure_learner = procedure_learner
        # TUI 모드엔 화면 방송이 없다. 외부 채널이 있으면 스케줄 결과가 거기로 간다(web 은 기동 시 fan_out 으로 덮는다)
        if scheduler is not None and ctx.notifier is not None:
            scheduler.set_notifier(ctx.notifier)
        ctx.scheduler = scheduler

        services = AppServices(
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
        from jarvis.core.tools.builtin.web_search import WebSearchTool
        from jarvis.core.tools.builtin.write_file import WriteFileTool
        from jarvis.core.tools.builtin.edit_file import EditFileTool
        from jarvis.core.tools.builtin.read_file import ReadFileTool
        from jarvis.core.tools.builtin.web_fetch import WebFetchTool
        from jarvis.core.tools.builtin.list_dir import ListDirTool
        from jarvis.core.tools.builtin.bash import BashTool
        from jarvis.core.tools.builtin.glob import GlobTool
        from jarvis.core.tools.builtin.grep import GrepTool
        from jarvis.core.tools.registry import ToolRegistry

        registry = ToolRegistry()
        for tool in (
            BashTool(), ReadFileTool(), WriteFileTool(), EditFileTool(), GlobTool(), GrepTool(),
            ListDirTool(), WebSearchTool(), WebFetchTool(),
        ):
            registry.register(tool)
        return registry

    def build_agent_tools(
        self, memory: "MemoryService | None" = None, loops: "OpenLoopStore | None" = None
    ) -> "ToolRegistry":
        """에이전트 정의가 이름으로 골라야 쓰는 도구. JARVIS(도구 목록 없음)의 레지스트리에는 넣지 않는다."""
        from jarvis.core.tools.housing import ProfileStore, housing_tools
        from jarvis.core.tools.registry import ToolRegistry

        registry = ToolRegistry()
        profiles = ProfileStore(memory) if memory is not None else None
        for tool in housing_tools(profiles=profiles, loops=loops):
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
        from jarvis.memory.consolidation.semantic_extract import llm_fact_extractor
        from jarvis.memory.long_term.procedural import SkillRegistryProcedures
        from jarvis.memory.consolidation import llm_summarizer
        from jarvis.memory.memory_service import MemoryService
        from jarvis.memory.retrieval import ScoringParams

        settings = self._settings
        mcfg = settings.memory
        embedder = self.build_embedder()
        from jarvis.memory.working.state import WorkingStore
        from jarvis.memory.stores.protocol import ItemStore

        item_store: ItemStore
        working_store: WorkingStore
        if mcfg.backend == "in_memory":
            from jarvis.memory.working.in_memory import InMemoryWorkingStore
            from jarvis.memory.stores.in_memory import InMemoryItemStore

            item_store = InMemoryItemStore()
            working_store = InMemoryWorkingStore()
        else:
            dsn = mcfg.postgres_dsn or settings.session.postgres_dsn
            if not dsn:
                raise ValueError("JARVIS_MEMORY__POSTGRES_DSN 또는 JARVIS_SESSION__POSTGRES_DSN 설정 필요")
            from jarvis.memory.working.postgres import PostgresWorkingStore
            from jarvis.memory.stores.postgres import PostgresItemStore

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
        from jarvis.core.scheduler.service import SchedulerService
        from jarvis.core.scheduler.loader import load_tasks

        return SchedulerService(
            tasks=load_tasks(scfg.schedules_dir),
            session_repo=session_repo,
            tool_registry=tool_registry,
            model=model_config,
            schedules_dir=scfg.schedules_dir,
            plugin_runner=plugin_runner,
            skill_registry=skill_registry,
        )

    def build_embedder(self) -> "Embedder | None":
        """메모리 의미 검색과 같은 약속 판정이 함께 쓰는 임베딩. JARVIS_MEMORY__EMBEDDING_* 설정 하나를 따른다."""
        from jarvis.model_layer.embeddings import build_embedder

        settings = self._settings
        mcfg = settings.memory
        return build_embedder(
            mcfg.embedding_provider,
            model=mcfg.embedding_model,
            dimensions=mcfg.embedding_dimensions,
            api_key=(mcfg.embedding_api_key or settings.llm.api_key or SecretStr("")).get_secret_value() or None,
            base_url=mcfg.embedding_base_url,
        )

    def build_openloop_store(self) -> "OpenLoopStore":
        """기본 jsonl. postgres 는 dsn 이 없으면 session/memory DSN 으로, 그래도 없으면 jsonl 로 물러선다."""
        settings = self._settings
        cfg = settings.openloop
        embedder = self.build_embedder()
        if cfg.backend == "in_memory":
            from jarvis.agent_layer.openloop import InMemoryOpenLoopStore

            return InMemoryOpenLoopStore(embedder)
        if cfg.backend == "postgres":
            dsn = cfg.postgres_dsn or settings.session.postgres_dsn or settings.memory.postgres_dsn
            if dsn:
                from jarvis.agent_layer.openloop import PostgresOpenLoopStore

                return PostgresOpenLoopStore(dsn=dsn, embedder=embedder)
        from jarvis.agent_layer.openloop import JsonlOpenLoopStore

        return JsonlOpenLoopStore(path=cfg.path, embedder=embedder)

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

    def build_push_store(self) -> "PushStore | None":
        """앱 Web Push 구독 저장소. VAPID 키 둘과 subject, Postgres 세션 저장소가 다 있을 때만."""
        cfg, session = self._settings.notify, self._settings.session
        keys = cfg.webpush_vapid_public_key and cfg.webpush_vapid_private_key is not None and cfg.webpush_subject
        if not keys:
            return None
        if session.persistence_backend != "postgres" or not session.postgres_dsn:
            logger.info("[Notify] web push off: 구독을 둘 Postgres 세션 저장소가 없다")
            return None
        from jarvis.core.notify.webpush import PushStore

        return PushStore(session.postgres_dsn)

    def build_notifier(self, push_store: "PushStore | None" = None) -> "Notify | None":
        """채널 설정이 하나도 없으면 None(기존 동작 그대로). 여럿이면 모두에 보낸다."""
        cfg = self._settings.notify
        from jarvis.core.notify import KIND_TYPES, discord_notifier, fan_out, only_kinds, slack_notifier, with_agents

        channels = []
        if cfg.slack_webhook_url is not None:
            channels.append(slack_notifier(cfg.slack_webhook_url.get_secret_value()))
            logger.info("[Notify] slack channel enabled")
        if cfg.discord_webhook_url is not None:
            text = discord_notifier(cfg.discord_webhook_url.get_secret_value())
            voice = self.build_discord_voice()
            if voice is None:
                channels.append(text)
            else:
                from jarvis.core.notify.discord_voice import voice_first

                types = {KIND_TYPES[k] for k in cfg.discord_voice_kinds if k in KIND_TYPES}
                channels.append(voice_first(voice, types, text))
            logger.info("[Notify] discord channel enabled" + (" (voice first)" if voice is not None else ""))
        if push_store is not None and cfg.webpush_vapid_private_key is not None:
            from jarvis.core.notify.webpush import pywebpush_sender, webpush_notifier

            send = pywebpush_sender(cfg.webpush_vapid_private_key.get_secret_value(), cfg.webpush_subject)
            channels.append(webpush_notifier(push_store, send))
            logger.info("[Notify] web push channel enabled")
        if not channels:
            return None
        notify = channels[0] if len(channels) == 1 else fan_out(*channels)
        return only_kinds(cfg.kinds, with_agents(self.agent_identities(), notify))

    def build_discord_voice(self) -> "DiscordVoice | None":
        """봇 토큰, 서버, 사용자 id 가 다 있고 TTS 와 discord.py 가 준비되면 음성. 하나라도 없으면 None(글로만)."""
        cfg = self._settings.notify
        if cfg.discord_bot_token is None or cfg.discord_guild_id is None or cfg.discord_user_id is None:
            return None
        import importlib.util

        if importlib.util.find_spec("discord") is None:
            logger.warning("[Notify] discord voice off, text only: uv sync --extra discord 가 필요하다")
            return None
        try:
            from jarvis.core.notify.discord_voice import DiscordGateway, DiscordVoice
            from jarvis.voice.speech_text import speech_text
            from jarvis.voice.service import VoiceService

            v = self._settings.voice
            tts = VoiceService.from_config(
                stt_provider="browser",
                tts_provider=cfg.discord_tts_provider,
                tts_options=v.tts_options(cfg.discord_tts_provider),
                english_tts_provider=v.english_tts_provider,
                english_tts_options=v.english_tts_options(),
            )
        except Exception as exc:
            logger.warning(f"[Notify] discord voice off, text only: {exc}")
            return None

        async def synthesize(text: str) -> bytes:
            return await tts.synthesize(text, v.tts_lang)

        gateway = DiscordGateway(cfg.discord_bot_token.get_secret_value(), cfg.discord_guild_id)
        return DiscordVoice(gateway, cfg.discord_user_id, synthesize, speech_text)

    def agent_identities(self) -> dict[str, tuple[str, str, str]]:
        """에이전트 id → (이름, 아바타 주소, 주색). 정의 파일을 읽는 곳은 load_agent_specs 하나다."""
        from jarvis.app.agent_registry import load_agent_specs
        from jarvis.memory.scope import MAIN_AGENT

        base = self._settings.notify.avatar_base_url.rstrip("/")
        brands = {MAIN_AGENT: (self._settings.brand.name, self._settings.brand.palette.primary)}
        brands.update({
            agent_id: (spec.name, spec.palette.primary)
            for agent_id, spec in load_agent_specs(self._settings.team.dir).items()
        })
        return {
            agent_id: (name, f"{base}/{agent_id}.png" if base else "", color)
            for agent_id, (name, color) in brands.items()
        }

    def build_subagents(
        self, ctx: AppContext, services: AppServices, agent_defs: list["AgentDefinition"]
    ) -> "OrchestrationService | None":
        """정의마다 위임 도구를 등록하고, 하나라도 실리면 orchestrate 도구까지. 팩토리 하나를 모든 정의가 공유한다."""
        settings = self._settings
        if not settings.agents.enabled or not agent_defs:
            return None
        from jarvis.core.multi_agent.service import OrchestrationService, load_supervisor_prompt
        from jarvis.core.multi_agent.orchestrate_tool import OrchestrateTool
        from jarvis.core.multi_agent.factory import AgentFactory

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
        from jarvis.core.slash.remember_cmd import make_remember_handler
        from jarvis.core.slash.dispatcher import SlashCommandDispatcher
        from jarvis.core.scheduler.classify import make_llm_classifier

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
        dispatcher.register_scoped(
            "remember",
            make_remember_handler(memory, session_repo),
            "내용 저장/검색/삭제 (list | search <키워드> | forget <id>)",
        )
        from jarvis.core.slash.patterns_cmd import make_patterns_handler

        dispatcher.register_scoped(
            "patterns", make_patterns_handler(memory), "지금 에이전트의 작업 패턴 (forget <이름>)"
        )
        from jarvis.core.slash.housing_cmd import make_housing_handler
        from jarvis.core.tools.housing import ProfileStore

        dispatcher.register_scoped(
            "housing", make_housing_handler(ProfileStore(memory)), "대출 자격용 주거 프로필 (set 항목=값 | clear)"
        )
        from jarvis.core.goals.tool import GOAL_TOOL, GoalTool

        goal_tool = tool_registry.get(GOAL_TOOL)
        if isinstance(goal_tool, GoalTool):
            from jarvis.core.slash.goal_cmd import make_goal_handler

            dispatcher.register_scoped(
                "goal", make_goal_handler(goal_tool), "지금 에이전트에게 계속 맡기는 목표 (<문장> | stop <문장>)"
            )
        if services.openloop_store is not None:
            from jarvis.core.slash.openloop_cmd import make_openloop_handler

            dispatcher.register(
                "openloop",
                make_openloop_handler(services.openloop_store),
                "추적 중인 약속/미완 작업 (done <id> | dismiss <id>)",
            )
        if services.user_model_store is not None:
            from jarvis.core.slash.usermodel_cmd import make_usermodel_handler
            from jarvis.agent_layer.usermodel import UserModelBuilder

            dispatcher.register_scoped(
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
            from jarvis.core.slash.journal_cmd import make_journal_handler
            from jarvis.agent_layer.journal import ReflectionJournaler

            dispatcher.register_scoped(
                "journal",
                make_journal_handler(ReflectionJournaler(model_config, memory)),
                "자기 성찰 저널 (write로 작성)",
            )

        from jarvis.core.slash.ops_cmd import (
            make_branch_handler,
            make_compact_handler,
            make_sessions_handler,
            make_tools_handler,
        )
        from jarvis.core.slash.procedures_cmd import make_procedures_handler
        from jarvis.core.slash.cleanup_cmd import make_cleanup_handler
        from jarvis.core.slash.export_cmd import make_export_handler
        from jarvis.core.slash.cost_cmd import make_cost_handler

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
        dispatcher.register_scoped(
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

            dispatcher.register_scoped(
                "orchestrate",
                make_orchestrate_handler(orchestration),
                "<pattern> [--agents a,b] [--promote] <작업>: 서브 에이전트들을 패턴으로 조율",
            )
        dispatcher.register("export", make_export_handler(session_repo), "현재 세션 대화 내보내기 (md | json)")
        dispatcher.register("cost", make_cost_handler(session_repo), "현재 세션 토큰 사용량·추정 비용 리포트")


def build_app(settings: "JarvisSettings") -> AppAssembly:
    """설정 하나로 앱 전체를 조립한다. TUI 와 Web 진입점이 부른다."""
    return InfraBuilder(settings).build()
