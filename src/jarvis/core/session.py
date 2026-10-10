from __future__ import annotations

import contextlib
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.agent_layer.harness import AgentHarness
from jarvis.agent_layer.memory.chain import MemoryMiddlewareChain
from jarvis.agent_layer.openloop import OpenLoop, OpenLoopStore
from jarvis.agent_layer.session.protocol import SessionRepo
from jarvis.agent_layer.thought import (
    DefaultThoughtComposer,
    ThoughtComposer,
    ThoughtEngine,
    ThoughtLog,
    ThoughtRequest,
)
from jarvis.agent_layer.thought.types import ThoughtFrame
from jarvis.agent_layer.types import (
    AgentEvent,
    AgentLoopConfig,
    InnerThoughtEvent,
    ProactiveMessageEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
)
from jarvis.agent_layer.usermodel import UserModelStore
from jarvis.core.external import ExternalEventInbox
from jarvis.core.plugins.runner import PluginRunner
from jarvis.core.policy.pipeline import AuthContext, PolicyDenied, PolicyResult, SecurityPipeline
from jarvis.core.proactive import (
    ActivityClock,
    EmitProactive,
    FeedbackLearner,
    ProactiveDecision,
    ProactiveMessage,
    ProactivityCore,
)
from jarvis.core.skills.registry import SkillRegistry
from jarvis.core.tools.registry import ToolRegistry
from jarvis.memory.scope import LOCAL_USER, MAIN_AGENT, MemoryScope, current_scope
from jarvis.model_layer.types import AssistantMessage, ModelConfig

# daemon 자율 성찰 시 user_input 대신 넣는 seed — 요청 없는 시점임을 모델에 알린다.
REFLECTION_SEED = (
    "(자율 성찰) 지금은 사용자의 직접 요청이 없는 시점이다. 최근 상황·맥락을 보고, "
    "사용자에게 먼저 알리거나 도울 가치가 있으면 decision을 act/ask로, 없으면 silent로 판단하라."
)

# E2 — daemon 자율 실행이 허용되는 읽기 전용 툴 화이트리스트(설계 §6 저위험 목록).
# 실제 실행은 이 목록 ∩ "승인 불필요(sandbox)" 이중 게이트를 통과해야만 한다.
AUTONOMOUS_SAFE_TOOLS = frozenset(
    {"read_file", "glob", "grep", "list_dir", "web_search", "web_fetch"}
)

AgentEventSink = Callable[[AgentEvent], Awaitable[None]]


class SessionBusy(Exception):
    """같은 세션에 이전 요청이 아직 돌고 있을 때 새 prompt 를 거부한다."""


BUSY_MESSAGE = "이전 요청을 아직 처리 중입니다. 끝나길 기다리거나 중단(abort)한 뒤 다시 보내세요."


class AgentSession:
    """
    모든 레이어를 연결하는 중추.
    Pi: AgentSession 완전 동일 역할.

    처리 순서:
    1. SecurityPipeline.run() — 4단계 강제 통과
    2. PluginRunner.emit_before_agent_start()
    3. SkillRegistry.expand() — /command 확장
    4. AgentHarness.run() — agent loop
    """

    def __init__(
        self,
        model: ModelConfig,
        session_id: str,
        security_pipeline: SecurityPipeline,
        plugin_runner: PluginRunner,
        memory_chain: MemoryMiddlewareChain,
        tool_registry: ToolRegistry,
        skill_registry: SkillRegistry,
        session_repo: SessionRepo,
        system_prompt: str | None = None,
        loop_config: AgentLoopConfig | None = None,
        agent_name: str | None = None,
        thought_engine: ThoughtEngine | None = None,
        thought_log: ThoughtLog | None = None,
        thought_composer: ThoughtComposer | None = None,
        proactivity_factory: Callable[[EmitProactive], ProactivityCore] | None = None,
        openloop_store: OpenLoopStore | None = None,
        activity_clock: ActivityClock | None = None,
        feedback_learner: FeedbackLearner | None = None,
        user_model_store: UserModelStore | None = None,
        external_inbox: ExternalEventInbox | None = None,
        external_detail_in_prompt: bool = False,
        inherit_scope: bool = False,
    ) -> None:
        self._security = security_pipeline
        # 서브 에이전트: 사용자는 인증이 아니라 위임한 부모의 범위(current_scope)에서 받는다.
        self._inherit_scope = inherit_scope
        self._plugins = plugin_runner
        self._tool_registry = tool_registry
        self._skill_registry = skill_registry
        self._session_id = session_id
        self._session_repo = session_repo
        self._memory_chain = memory_chain
        self._thought_engine = thought_engine
        self._thought_log = thought_log
        self._thought_composer = thought_composer or DefaultThoughtComposer()
        self._openloop_store = openloop_store
        self._activity_clock = activity_clock
        self._feedback_learner = feedback_learner
        self._user_model_store = user_model_store
        self._external_inbox = external_inbox
        self._external_detail_in_prompt = external_detail_in_prompt
        # 코어는 세션별 emit에 바인딩되어야 하므로 팩토리로 주입받아 여기서 생성.
        self._proactivity: ProactivityCore | None = (
            proactivity_factory(self._emit_proactive) if proactivity_factory else None
        )

        self._rate_counters: dict[str, deque[float]] = {}
        # prompt 진입 즉시 켜고 메인 루프가 끝날 때 끈다. harness.is_running 은 inner thought
        # 이후에야 켜져서 그 틈에 두 요청이 동시에 통과해 히스토리를 섞는다.
        self._busy = False
        # 마지막으로 인증된 사용자. 세션 종료 요약처럼 턴 바깥에서 쓰는 메모리 범위의 근거.
        self._last_user_id: str | None = None

        self._harness = AgentHarness(
            model=model,
            session_id=session_id,
            memory_chain=memory_chain,
            session_repo=session_repo,
            system_prompt=system_prompt,
            tools=tool_registry.to_llm_tools(),
            loop_config=loop_config,
            agent_name=agent_name,
        )

    def subscribe(self, listener: AgentEventSink) -> Callable[[], None]:
        return self._harness.subscribe(listener)

    async def prompt(
        self,
        raw_input: str,
        credentials: dict | None = None,
    ) -> AssistantMessage | None:
        if self._busy:
            raise SessionBusy(BUSY_MESSAGE)
        self._busy = True
        outer_scope = current_scope.get()
        try:
            return await self._prompt(raw_input, credentials or {})
        except BaseException:
            # run_main 진입 전 실패(검증·인증·rate limit·사고) — run_main 의 finally 가 못 끈다.
            self._busy = False
            raise
        finally:
            current_scope.set(outer_scope)  # 이 세션이 설정한 범위가 호출자(부모 턴)에 새지 않도록

    async def _prompt(self, raw_input: str, creds: dict) -> AssistantMessage | None:
        # 사용자 활동 기록 — idle 트리거가 "조용해진 시점"을 알도록 리셋한다.
        if self._activity_clock is not None:
            self._activity_clock.touch()

        validated, auth_ctx, policy_result = await self._security.run(
            raw_input=raw_input,
            credentials=creds,
            requested_tools=self._tool_registry.list_all() and [t.name for t in self._tool_registry.list_all()],
        )

        if policy_result.rate_limit is not None:
            self._check_rate_limit(auth_ctx.user_id, policy_result.rate_limit)

        inherited = current_scope.get() if self._inherit_scope else None
        self._last_user_id = (inherited.user_id if inherited and inherited.user_id else None) or auth_ctx.user_id
        current_scope.set(self.memory_scope)

        expanded = self._skill_registry.expand(validated.sanitized)

        frame = await self._run_inner_thought(expanded)
        inner_thought_prompt = self._thought_composer.compose(frame) or None if frame is not None else None

        await self._plugins.emit_before_agent_start(expanded, {"session_id": self._session_id})

        tool_executor = self._make_tool_executor(auth_ctx, policy_result)
        # 턴마다 도구 목록을 다시 읽는다. 승인된 절차처럼 세션 생성 뒤 등록된 도구가 보이도록
        self._harness._tools = self._tool_registry.to_llm_tools()

        async def run_main() -> AssistantMessage | None:
            try:
                result = await self._harness.run(
                    user_input=expanded,
                    tool_executor=tool_executor,
                    extra_context={
                        "user_id": self._last_user_id,
                        "roles": list(auth_ctx.roles),
                        "inner_thought_prompt": inner_thought_prompt,
                    },
                )
                if result:
                    result = await self._plugins.emit_on_message_end(result)
                return result
            finally:
                # Dual-Channel 백그라운드 모드에서는 prompt() 가 먼저 돌아오므로 여기서 꺼야 한다.
                self._busy = False

        # Dual-Channel: proactivity가 있으면 needs_background 시 filler 즉시 발화 후
        # 백그라운드 수행(반환 None). 없거나 즉시 모드면 현재 동작 그대로.
        if self._proactivity is not None:
            return await self._proactivity.dispatch_request(frame, run_main)
        return await run_main()

    async def reflect(self) -> ProactiveDecision | None:
        """daemon 자율 성찰(B3) — 요청 없이 한 번 성찰해 먼저 말할지 게이팅한다.

        엔진/ proactivity가 없으면 no-op(None). 게이팅 통과 시 core.reflect가
        ProactiveMessageEvent를 push한다.

        외부 이벤트(Phase 3)가 있으면 inbox를 여기서 drain해 사고에 먹인다 —
        drain-once이므로 여러 세션이 성찰해도 이벤트당 발화는 1회뿐이다.
        """
        if self._thought_engine is None or self._proactivity is None:
            return None
        frame = await self._run_inner_thought(
            REFLECTION_SEED,
            mode="reflection",
            external_events=self._drain_external_events(),
        )
        if frame is None:
            return None
        decision = await self._proactivity.reflect(
            frame, session_id=self._session_id, execute=self._execute_autonomous
        )
        if not decision.speak:
            # 🔔 가 안 뜨는 이유(임계치 미달, 쿨다운, utterance 비움)를 로그에서 볼 수 있게.
            print(f"[Thought] proactive silent: {decision.reason}")
        return decision

    async def _execute_autonomous(self, actions: list[Any]) -> str:
        """저위험 자율 행동(E2)을 실행하고 사람이 읽을 요약을 반환.

        이중 안전 게이트: (1) AUTONOMOUS_SAFE_TOOLS 화이트리스트 ∩
        (2) sandbox 승인 불필요. 둘 다 통과한 tool 행동만 실행한다(고위험·외부
        변경·승인 대상은 절대 자율 실행하지 않음 — 요청 없는 시점엔 승인 주체 없음).
        """
        import uuid

        done: list[str] = []
        for action in actions:
            if action.kind != "tool" or not action.tool_name:
                continue
            if action.tool_name not in AUTONOMOUS_SAFE_TOOLS:
                continue
            if self._security.sandbox.is_approval_required(action.tool_name):
                continue

            call_id = uuid.uuid4().hex[:12]
            await self._harness.emit_event(
                ToolExecutionStartEvent(
                    tool_call_id=call_id, tool_name=action.tool_name, args=action.args
                )
            )
            is_error = True
            try:
                result = await self._tool_registry.execute(
                    call_id, action.tool_name, action.args
                )
                is_error = bool(getattr(result, "is_error", False))
            except Exception:
                is_error = True
            await self._harness.emit_event(
                ToolExecutionEndEvent(
                    tool_call_id=call_id, tool_name=action.tool_name, is_error=is_error
                )
            )
            if not is_error:
                done.append(f"· {action.description}")

        if not done:
            return ""
        return "(미리 해둠) " + " / ".join(done)

    def _drain_external_events(self) -> list[str]:
        """외부 이벤트 inbox를 비워 사고 프롬프트용 한 줄 목록으로 변환.

        inbox가 없으면(소스 미설정) 빈 목록 — 기존 동작과 완전히 동일하다.
        external_detail_in_prompt=False(기본)면 원문 대신 제목만 싣는다 —
        메일 본문 등이 사고 로그·LTM에 축적되는 것을 막는다.
        """
        if self._external_inbox is None:
            return []
        return [
            event.as_line(include_detail=self._external_detail_in_prompt)
            for event in self._external_inbox.drain()
        ]

    async def _run_inner_thought(
        self,
        user_input: str,
        mode: str = "request",
        external_events: list[str] | None = None,
    ) -> ThoughtFrame | None:
        """
        메타인지 1회 — 요청 시점(expand 직후) 또는 daemon 성찰(mode="reflection").

        사고 프레임을 생성·기록·이벤트로 노출하고 그 프레임을 반환한다. 프레임은
        ① composer 조립(컨텍스트 증강)과 ② proactivity 판단에 쓰인다.
        엔진이 없거나(비활성) 사고가 생략/실패하면 None을 돌려 메인 턴을 그대로 진행.
        """
        if self._thought_engine is None:
            return None

        frame = await self._thought_engine.think(
            ThoughtRequest(
                user_input=user_input,
                history=await self._session_repo.get_messages(self._session_id),
                session_id=self._session_id,
                open_loops=await self._load_open_loops(),
                user_model=await self._load_user_model(),
                external_events=external_events or [],
                mode=mode,  # type: ignore[arg-type]
            )
        )
        if frame is None:
            return None

        # 성찰은 기존 약속을 보는 자리다. 모델이 매번 바꿔 말한 항목을 저장하면 같은 약속이 쌓인다.
        if mode == "request":
            await self._persist_open_loops(frame)

        await self._harness.emit_event(
            InnerThoughtEvent(
                session_id=self._session_id,
                interpretation=frame.interpretation,
                decision=frame.decision,
                confidence=frame.confidence,
                frame=frame.model_dump(),
            )
        )
        if self._thought_log is not None:
            await self._thought_log.store(frame, self._session_id)

        return frame

    async def _emit_proactive(self, message: ProactiveMessage) -> None:
        """ProactivityCore의 push 콜백 — ProactiveMessage → ProactiveMessageEvent."""
        await self._harness.emit_event(
            ProactiveMessageEvent(
                session_id=self._session_id,
                text=message.text,
                kind=message.kind,
                message_id=message.id,
            )
        )

    async def record_feedback(self, accepted: bool) -> None:
        """proactive 발화에 대한 사용자 피드백(수락/무시)을 학습기에 기록 (C3).

        채널 무관(web 버튼 / TUI 키 / voice) — UI가 이 진입점으로 신호를 모은다.
        """
        if self._feedback_learner is not None:
            self._feedback_learner.record(accepted)

    async def _load_open_loops(self) -> list[str]:
        """열린 open-loop 설명을 사고 컨텍스트로 주입(없거나 store 미설정이면 빈 목록)."""
        if self._openloop_store is None:
            return []
        try:
            loops = await self._openloop_store.list_open(session_id=self._session_id)
        except Exception:
            return []
        return [loop.description for loop in loops]

    async def _load_user_model(self) -> str:
        """증류된 사용자 모델을 사고 컨텍스트 블록으로 주입(없으면 빈 문자열)."""
        if self._user_model_store is None:
            return ""
        try:
            model = await self._user_model_store.get()
        except Exception:
            return ""
        return model.as_context() if model is not None else ""

    async def _persist_open_loops(self, frame: ThoughtFrame) -> None:
        """사고가 새로 감지한 open-loop를 저장(중복은 store가 건너뜀). 부가 작업이라 실패 무시."""
        if self._openloop_store is None or not frame.open_loops:
            return
        for desc in frame.open_loops:
            text = desc.strip()
            if not text:
                continue
            with contextlib.suppress(Exception):
                await self._openloop_store.add_unique(
                    OpenLoop(description=text, origin_session=self._session_id)
                )

    def _check_rate_limit(self, user_id: str, rate_limit: int, window: float = 60.0) -> None:
        """슬라이딩 윈도우(window초)에서 rate_limit 초과 시 PolicyDenied."""
        now = time.monotonic()
        if user_id not in self._rate_counters:
            self._rate_counters[user_id] = deque()
        timestamps = self._rate_counters[user_id]
        while timestamps and now - timestamps[0] > window:
            timestamps.popleft()
        if len(timestamps) >= rate_limit:
            raise PolicyDenied(f"Rate limit exceeded: {rate_limit} requests/{int(window)}s for user '{user_id}'")
        timestamps.append(now)

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    def register_tool(self, tool: Any) -> None:
        """세션 생성 뒤 도구를 더한다. harness 가 생성 시점 스냅샷을 쓰므로 LLM 도구 목록도 갱신한다."""
        self._tool_registry.register(tool)
        self._harness._tools = self._tool_registry.to_llm_tools()

    @property
    def memory_scope(self) -> MemoryScope:
        """이 세션이 기억을 읽고 쓰는 범위. 사용자는 마지막 인증값, 없으면 로컬 사용자."""
        return MemoryScope(
            user_id=self._last_user_id or LOCAL_USER,
            agent_id=self._harness._agent_name or MAIN_AGENT,
            session_id=self._session_id,
        )

    @property
    def agent_name(self) -> str | None:
        return self._harness._agent_name

    @agent_name.setter
    def agent_name(self, name: str | None) -> None:
        self._harness._agent_name = name

    def abort(self) -> None:
        self._harness.abort()

    @property
    def is_running(self) -> bool:
        return self._busy or self._harness.is_running

    def _make_tool_executor(self, auth_ctx: AuthContext, policy_result: PolicyResult):
        allowed = policy_result.allowed_tools

        async def executor(tool_call_id: str, tool_name: str, params: dict[str, Any]) -> Any:
            if "*" not in allowed and tool_name not in allowed:
                from jarvis.model_layer.types import TextContent, ToolResultMessage

                return ToolResultMessage(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    content=[TextContent(text=f"Tool '{tool_name}' is not permitted for this user")],
                    is_error=True,
                )

            hook_result = await self._plugins.emit_before_tool_call(tool_name, params, auth_ctx)
            if hook_result and hook_result.get("block"):
                from jarvis.model_layer.types import TextContent, ToolResultMessage

                return ToolResultMessage(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    content=[TextContent(text=hook_result.get("reason", "Blocked by plugin"))],
                    is_error=True,
                )

            if not await self._security.sandbox.authorize(tool_name, params):
                from jarvis.model_layer.types import TextContent, ToolResultMessage

                return ToolResultMessage(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    content=[TextContent(text=f"Execution of '{tool_name}' was denied")],
                    is_error=True,
                )

            from jarvis.core.tools.registry import ToolContext

            context = ToolContext(scope=self.memory_scope, session_id=self._session_id, user_id=self._last_user_id)
            result = await self._tool_registry.execute(tool_call_id, tool_name, params, context=context)
            await self._plugins.emit_after_tool_call(tool_name, params, {"is_error": result.is_error})
            return result

        return executor
