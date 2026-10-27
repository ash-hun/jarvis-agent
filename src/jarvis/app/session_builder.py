"""[app] SessionBuilder: AgentProfile 과 앱 서비스로 AgentSession 하나를 조립한다(TUI, Web 공용)."""

import uuid
from typing import TYPE_CHECKING
from dataclasses import dataclass
from collections.abc import Awaitable, Callable

from jarvis.common.logger import get_logger

if TYPE_CHECKING:
    from jarvis.agent_layer.thought import ThoughtComposer, ThoughtEngine, ThoughtLog, ThoughtSink
    from jarvis.agent_layer.openloop.judge import OpenLoopJudge
    from jarvis.agent_layer.thought.router import ThoughtRouter
    from jarvis.core.tools.registry import ToolRegistry
    from jarvis.agent_layer.openloop import LoopExpiry
    from jarvis.app.agent_profile import AgentProfile
    from jarvis.app.app_services import AppServices
    from jarvis.app.app_context import AppContext
    from jarvis.core.session import AgentSession
    from jarvis.model_layer.types import Message

logger = get_logger(__name__)


@dataclass(frozen=True)
class ThoughtParts:
    """사고가 켜져 있을 때 세션에 꽂는 세 부품. 꺼져 있으면 모두 None."""

    engine: "ThoughtEngine | None" = None
    log: "ThoughtLog | None" = None
    composer: "ThoughtComposer | None" = None
    router: "ThoughtRouter | None" = None
    loop_judge: "OpenLoopJudge | None" = None


class SessionBuilder:
    """세션 id 하나를 받아 사고, proactive, open loop, 알림까지 연결된 AgentSession 을 만든다."""

    def __init__(self, ctx: "AppContext", services: "AppServices", profile: "AgentProfile") -> None:
        self._ctx = ctx
        self._services = services
        self._profile = profile

    @property
    def profile(self) -> "AgentProfile":
        return self._profile

    def build(
        self, session_id: str, services: "AppServices | None" = None, inherit_scope: bool = False
    ) -> "AgentSession":
        """services 를 주면(세션 전용 보안 파이프라인) 그것으로, 아니면 앱 기본 서비스로 만든다.

        inherit_scope 는 다른 에이전트가 부른 대화 세션이다. 사용자를 인증이 아니라 부른 쪽 범위에서 받는다.
        """
        from jarvis.core.session import AgentSession

        svc = services or self._services
        settings = self._ctx.settings
        thought = self.thought_parts(svc)
        profile = self._profile
        session = AgentSession(
            model=profile.model,
            session_id=session_id,
            security_pipeline=svc.pipeline,
            plugin_runner=svc.plugin_runner,
            memory=svc.memory,
            tool_registry=self.tool_registry(),
            skill_registry=svc.skill_registry,
            session_repo=self._ctx.session_repo,
            system_prompt=profile.system_prompt,
            # main 은 이름 없이 둔다. 기억 범위가 기존 데이터와 같은 main 으로 남는다
            agent_name=None if profile.is_main else profile.agent_id,
            thought_engine=thought.engine,
            thought_log=thought.log,
            thought_composer=thought.composer,
            thought_timing=self._profile.thought.request_timing,
            thought_wait_sec=self._profile.thought.wait_sec,
            proactivity_factory=self._profile.proactivity_factory(),
            openloop_store=svc.openloop_store,
            openloop_expiry=self.openloop_expiry(),
            activity_clock=svc.activity_clock,
            feedback_learner=self._profile.feedback_learner,
            user_model_store=svc.user_model_store,
            external_inbox=svc.external_inbox,
            external_detail_in_prompt=settings.external.store_detail_in_log,
            inherit_scope=inherit_scope,
            thought_router=thought.router,
            loop_judge=thought.loop_judge,
        )
        # 먼저 거는 말은 열린 화면뿐 아니라 외부 채널에도 간다. 서브 에이전트와 스케줄 세션은 이 경로를 타지 않는다
        if self._ctx.notifier is not None:
            from jarvis.core.notify import proactive_forwarder

            session.subscribe(proactive_forwarder(self._ctx.notifier, self._profile.agent_id))
        return session

    def tool_registry(self) -> "ToolRegistry":
        """정의에 도구 목록이 있으면 그 도구만 담은 레지스트리, 없으면 앱 레지스트리 그대로."""
        registry = self._ctx.tool_registry
        if not self._profile.tools:
            return registry
        from jarvis.core.tools.task_pattern import TASK_PATTERN_TOOL
        from jarvis.core.tools.registry import PickedToolRegistry
        from jarvis.app.agent_conversation import ASK_AGENT_TOOL
        from jarvis.core.procedures import TOOL_PREFIX

        # 팀 대화와 작업 패턴 저장은 정의에 적지 않아도 늘 쓴다. 팀이 한 명이면 팀 대화는 등록돼 있지 않다.
        # 승인된 절차도 보인다. 절차의 단계는 이 창을 거쳐 실행되므로 정의에 없는 도구는 그 단계에서 멈춘다
        return PickedToolRegistry(
            (registry, self._ctx.agent_tools),
            (*self._profile.tools, ASK_AGENT_TOOL, TASK_PATTERN_TOOL),
            prefixes=(TOOL_PREFIX,),
        )

    def thought_parts(self, services: "AppServices") -> ThoughtParts:
        """사고 엔진(분리된 사고 모델), 사고 로그 싱크, composer. 사고가 꺼져 있으면 빈 ThoughtParts."""
        tcfg = self._profile.thought
        if not tcfg.enabled:
            return ThoughtParts()

        from jarvis.agent_layer.thought import (
            DefaultThoughtComposer,
            InnerThoughtEngine,
            InterpretationOnlyComposer,
            LTMThoughtSink,
            ThoughtLog,
            ThoughtPromptTemplate,
            WorkingNotesSink,
        )
        from jarvis.agent_layer.thought.prompt import DEFAULT_REFLECTION_TEMPLATE

        engine: ThoughtEngine = InnerThoughtEngine(
            model=self._profile.thought_model(),
            template=ThoughtPromptTemplate.load(tcfg.prompt_path),
            reflection_template=ThoughtPromptTemplate.load(
                tcfg.reflection_prompt_path, default=DEFAULT_REFLECTION_TEMPLATE
            ),
            recall=services.memory.recall_messages,
            recall_limit=tcfg.recall_limit,
            skip_if_shorter_than=tcfg.skip_if_shorter_than,
            history_window=tcfg.history_turns,
            history_chars=tcfg.history_chars,
            persona=self._profile.brand.persona,
        )
        decision_name = self._profile.proactive.decision_model
        if decision_name:
            from jarvis.agent_layer.thought.decision_gate import DecisionGatedEngine
            from jarvis.model_layer.decision import DecisionModel

            decision = DecisionModel(decision_name, self._profile.proactive.decision_base_url)
            engine = DecisionGatedEngine(
                engine,
                decision,
                utterance_model=self._profile.thought_model(),
                persona=self._profile.brand.persona,
            )
        # 설정된 싱크만, 모르는 이름은 무시한다
        sink_factories: dict[str, Callable[[], ThoughtSink]] = {
            "ltm": lambda: LTMThoughtSink(services.memory),
            "stm": lambda: WorkingNotesSink(services.memory),
        }
        log = ThoughtLog([sink_factories[name]() for name in tcfg.log_sinks if name in sink_factories])
        composers: dict[str, Callable[[], ThoughtComposer]] = {
            "default": DefaultThoughtComposer,
            "interpretation_only": InterpretationOnlyComposer,
        }
        composer = composers.get(tcfg.composer, DefaultThoughtComposer)()
        from jarvis.agent_layer.openloop.judge import OpenLoopJudge

        # 약속 추적은 사고와 따로 매 턴 돈다. 저장소가 없으면 세션이 부르지 않는다
        loop_judge = OpenLoopJudge(self._profile.thought_model())
        return ThoughtParts(
            engine=engine, log=log, composer=composer, router=self.thought_router(), loop_judge=loop_judge
        )

    def thought_router(self) -> "ThoughtRouter | None":
        tcfg = self._profile.thought
        if not tcfg.router_model:
            return None
        from jarvis.agent_layer.thought.router import ThoughtRouter
        from jarvis.model_layer.decision import DecisionModel

        decision = DecisionModel(tcfg.router_model, tcfg.router_base_url, timeout=tcfg.router_timeout_sec)
        return ThoughtRouter(decision, threshold=tcfg.router_threshold)

    def openloop_expiry(self) -> "LoopExpiry":
        from jarvis.agent_layer.openloop import LoopExpiry

        cfg = self._ctx.settings.openloop
        return LoopExpiry(grace_ms=cfg.expire_after_sec * 1000, max_age_ms=cfg.max_age_sec * 1000)

    def new_session_factory(self) -> "Callable[[], Awaitable[AgentSession]]":
        """Ctrl+N: 새 UUID 세션을 저장소에 만들고 조립한다. TUI on_mount 뒤에만 부른다."""

        async def factory() -> "AgentSession":
            new_id = str(uuid.uuid4())
            await self._ctx.session_repo.create(session_id=new_id)
            return self.build(new_id)

        return factory

    def branch_factory(self) -> "Callable[[str], Awaitable[AgentSession]]":
        """Ctrl+F: 부모 세션의 메시지를 복사한 분기 세션을 조립한다."""

        async def factory(parent_session_id: str) -> "AgentSession":
            repo = self._ctx.session_repo
            if hasattr(repo, "create_branch"):
                meta = await repo.create_branch(parent_session_id)
            else:
                meta = await repo.create(session_id=str(uuid.uuid4()))
            return self.build(meta.session_id)

        return factory


async def learn_procedures(ctx: "AppContext", session_id: str, messages: "list[Message]") -> list[str]:
    """세션 종료 때 절차 학습. 학습기가 없거나 실패하면 빈 목록(요약 저장을 막지 않는다)."""
    if ctx.procedure_learner is None or not messages:
        return []
    try:
        return await ctx.procedure_learner.learn(session_id, messages)
    except Exception as exc:
        logger.info(f"[Procedures] learning failed (non-fatal): {exc}")
        return []
