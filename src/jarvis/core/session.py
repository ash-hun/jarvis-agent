"""[core] 에이전트 세션. 보안, 플러그인, 스킬, 사고, proactive 를 묶어 한 턴과 자율 성찰을 실행한다."""

import time
import asyncio
import contextlib
from collections import deque
from datetime import datetime
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol, cast

from jarvis.agent_layer.types import (
    AgendaChangedEvent,
    AgentEvent,
    AgentLoopConfig,
    InnerThoughtEvent,
    ProactiveMessageEvent,
    ThoughtEndEvent,
    ThoughtRouteEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
)
from jarvis.agent_layer.openloop import (
    LoopExpiry,
    OpenLoop,
    OpenLoopStore,
    cancelled_ids,
    close_expired,
    grounded,
    matching_ids,
    parse_loop_note,
    refers_to,
    split_evidence,
)
from jarvis.core.proactive import (
    ActivityClock,
    EmitProactive,
    FeedbackLearner,
    ProactiveDecision,
    ProactiveMessage,
    ProactivityCore,
)
from jarvis.agent_layer.thought import (
    DefaultThoughtComposer,
    ThoughtComposer,
    ThoughtEngine,
    ThoughtLog,
    ThoughtRequest,
)
from jarvis.model_layer.types import AssistantMessage, ModelConfig, TextContent, ToolResultMessage, UserMessage
from jarvis.core.policy.pipeline import AuthContext, PolicyDenied, PolicyResult, SecurityPipeline
from jarvis.agent_layer.session.protocol import PROACTIVE_ACK_ENTRY, SessionRepo
from jarvis.agent_layer.thought.types import ProactiveAction, ThoughtFrame
from jarvis.agent_layer.thought.router import RouteVerdict, ThoughtRouter
from jarvis.memory.scope import LOCAL_USER, MAIN_AGENT, MemoryScope
from jarvis.core.tools.registry import JarvisTool, ToolRegistry
from jarvis.agent_layer.thought.reply import ReplyClassifier
from jarvis.agent_layer.openloop.judge import OpenLoopJudge
from jarvis.agent_layer.openloop.types import same_loop
from jarvis.agent_layer.usermodel import UserModelStore
from jarvis.memory.memory_service import MemoryService
from jarvis.core.skills.registry import SkillRegistry
from jarvis.agent_layer.harness import AgentHarness
from jarvis.core.external import ExternalEventInbox
from jarvis.core.plugins.runner import PluginRunner
from jarvis.common.logger import get_logger

# daemon 자율 성찰 시 user_input 대신 넣는 seed. 요청 없는 시점임을 모델에 알린다.
REFLECTION_SEED = (
    "(자율 성찰) 지금은 사용자의 직접 요청이 없는 시점이다. 최근 상황·맥락을 보고, "
    "사용자에게 먼저 알리거나 도울 가치가 있으면 decision을 act/ask로, 없으면 silent로 판단하라."
)

# E2. daemon 자율 실행이 허용되는 읽기 전용 툴 화이트리스트(설계 §6 저위험 목록).
# 실제 실행은 이 목록 ∩ "승인 불필요(sandbox)" 이중 게이트를 통과해야만 한다.
AUTONOMOUS_SAFE_TOOLS = frozenset(
    {"read_file", "glob", "grep", "list_dir", "web_search", "web_fetch"}
)

AgentEventSink = Callable[[AgentEvent], Awaitable[None]]
# 하네스가 도구 호출마다 부르는 실행기: (tool_call_id, tool_name, params) → 결과 메시지
ToolExecutor = Callable[[str, str, dict[str, Any]], Awaitable[ToolResultMessage]]
ThoughtMode = Literal["request", "reflection"]

# 승인이 필요한 도구를 모델이 "할 수 없다"며 방법 안내로 피하지 않게 한다. 승인은 시스템이 묻는다
APPROVAL_RULE = (
    "[도구 승인] {tools} 는 실행 전에 시스템이 사용자에게 승인을 묻는다. 사용자가 실행을 요청하면 이 도구를 "
    "직접 호출한다. 할 수 없다고 하거나 사용자가 직접 하는 방법을 안내하는 것으로 대신하지 않는다. "
    "앞에서 승인되지 않았어도 새 요청이면 다시 호출해 승인을 구한다."
)
# 거부 결과가 "도구를 못 쓴다"로 읽히면 다음 턴부터 모델이 실행을 포기한다
DENIED_RESULT = {
    "deny": "사용자가 '{tool}' 실행을 거부해 실행하지 않았다.",
    "timeout": "'{tool}' 승인 요청에 사용자가 시간 안에 답하지 않아 실행하지 않았다.",
}
DENIED_RESULT_TAIL = (
    " 도구는 계속 쓸 수 있다. 실행하지 않았다고 짧게 알리고, 사용자가 직접 하는 방법을 안내하는 것으로 대신하지 않는다."
)

logger = get_logger(__name__)


class SessionBusy(Exception):
    """같은 세션에 이전 요청이 아직 돌고 있을 때 새 prompt 를 거부한다."""


class TurnHook(Protocol):
    """턴마다 끼어드는 확장(Focus 모드). 시스템 프롬프트에 맥락을 더하고, 턴 앞뒤에 뒤에서 일을 돌린다."""

    def system_addendum(self) -> str | None: ...

    async def before_turn(self, user_input: str) -> None: ...

    async def after_turn(self, user_input: str, reply: str) -> None: ...


THOUGHT_WAIT_SEC = 3.0
# 성찰이 같은 말을 바꿔 다시 하지 않도록 최근 🔔 몇 개를 보여준다
RECENT_PROACTIVE_MAX = 3
# 이 시간 안에 한 답을 되풀이하는 🔔 는 보내지 않는다
REPEAT_ANSWER_SEC = 600
# 대화, 약속, 이벤트가 그대로면 성찰을 다시 하지 않는다. 기한이 다가오는 것은 이 간격마다 다시 본다
REFLECT_REFRESH_SEC = 900

BUSY_MESSAGE = "이전 요청을 아직 처리 중입니다. 끝나길 기다리거나 중단(abort)한 뒤 다시 보내세요."
# 화면은 agent_end 를 받자마자 다음 말을 보낼 수 있다. 그때 세션은 대화 저장 같은 마무리 중이라(수백 ms)
# 바로 거절하지 않고 이만큼 기다린다. 긴 작업 도중에 온 요청은 기다린 뒤에도 거절한다
BUSY_GRACE_SEC = 3.0


class AgentSession:
    """모든 레이어를 연결하는 중추. Pi: AgentSession 완전 동일 역할.

    처리 순서:
    1. SecurityPipeline.run(): 4단계 강제 통과
    2. PluginRunner.emit_before_agent_start()
    3. SkillRegistry.expand(): /command 확장
    4. AgentHarness.run(): agent loop
    """

    def __init__(
        self,
        model: ModelConfig,
        session_id: str,
        security_pipeline: SecurityPipeline,
        plugin_runner: PluginRunner,
        tool_registry: ToolRegistry,
        skill_registry: SkillRegistry,
        session_repo: SessionRepo,
        system_prompt: str | None = None,
        loop_config: AgentLoopConfig | None = None,
        agent_name: str | None = None,
        thought_engine: ThoughtEngine | None = None,
        thought_log: ThoughtLog | None = None,
        thought_composer: ThoughtComposer | None = None,
        thought_timing: str = "race",
        thought_wait_sec: float = THOUGHT_WAIT_SEC,
        proactivity_factory: Callable[[EmitProactive], ProactivityCore] | None = None,
        openloop_store: OpenLoopStore | None = None,
        openloop_expiry: LoopExpiry | None = None,
        activity_clock: ActivityClock | None = None,
        feedback_learner: FeedbackLearner | None = None,
        user_model_store: UserModelStore | None = None,
        external_inbox: ExternalEventInbox | None = None,
        external_detail_in_prompt: bool = False,
        inherit_scope: bool = False,
        memory: MemoryService | None = None,
        thought_router: ThoughtRouter | None = None,
        loop_judge: OpenLoopJudge | None = None,
        reply_classifier: ReplyClassifier | None = None,
    ) -> None:
        self._security = security_pipeline
        # 서브 에이전트: 사용자는 인증이 아니라 부른 쪽 범위(prompt 의 caller_scope)에서 받는다.
        self._inherit_scope = inherit_scope
        self._plugins = plugin_runner
        self._tool_registry = tool_registry
        self._skill_registry = skill_registry
        self._session_id = session_id
        self._session_repo = session_repo
        self._thought_engine = thought_engine
        self._thought_log = thought_log
        self._thought_composer = thought_composer or DefaultThoughtComposer()
        self._thought_timing = thought_timing
        self._thought_wait_sec = thought_wait_sec
        self._late_thoughts: set[asyncio.Task[Any]] = set()  # 참조를 잃으면 GC 가 끊는다
        # router 가 있으면 요청 턴의 사고를 think 일 때만 응답과 함께 띄우고, 결과는 다음 턴에 한 번 넣는다
        self._thought_router = thought_router
        self._pending_frame: ThoughtFrame | None = None
        self._loop_judge = loop_judge
        self._loop_tasks: set[asyncio.Task[Any]] = set()
        self._turn_hook: TurnHook | None = None
        self._hook_tasks: set[asyncio.Task[Any]] = set()
        self._openloop_store = openloop_store
        self._openloop_expiry = openloop_expiry
        self._activity_clock = activity_clock
        self._feedback_learner = feedback_learner
        self._user_model_store = user_model_store
        self._external_inbox = external_inbox
        self._external_detail_in_prompt = external_detail_in_prompt
        self._recent_proactive: deque[str] = deque(maxlen=RECENT_PROACTIVE_MAX)
        self._proactive_restored = False
        # 사용자가 이 세션에서 말한 적이 있는가. 없으면 성찰할 대화가 없어 먼저 말하지 않는다
        self._user_spoke = False
        self._last_proactive_id: str | None = None  # 피드백이 어느 🔔 에 대한 답인지
        # 먼저 건넨 말 뒤 사용자의 첫 말로 학습한다. 묻지 않는다. 기다리는 말이 없으면 None
        self._reply_classifier = reply_classifier
        self._awaiting_text: str | None = None
        self._feedback_tasks: set[asyncio.Task[Any]] = set()
        # 지난 성찰의 입력. 같으면 사고 모델을 부르지 않는다
        self._reflect_key: tuple[Any, ...] | None = None
        # 코어는 세션별 emit에 바인딩되어야 하므로 팩토리로 주입받아 여기서 생성.
        self._proactivity: ProactivityCore | None = (
            proactivity_factory(self._emit_proactive) if proactivity_factory else None
        )

        self._rate_counters: dict[str, deque[float]] = {}
        # prompt 진입 즉시 켜고 메인 루프가 끝날 때 끈다. harness.is_running 은 inner thought
        # 이후에야 켜져서 그 틈에 두 요청이 동시에 통과해 히스토리를 섞는다.
        self._busy = False
        self._idle = asyncio.Event()
        self._idle.set()
        # 마지막으로 인증된 사용자. 세션 종료 요약처럼 턴 바깥에서 쓰는 메모리 범위의 근거.
        self._last_user_id: str | None = None

        self._harness = AgentHarness(
            model=model,
            session_id=session_id,
            session_repo=session_repo,
            memory=memory,
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
        credentials: dict[str, Any] | None = None,
        caller_scope: MemoryScope | None = None,
    ) -> AssistantMessage | None:
        """caller_scope 는 이 세션을 부른 쪽(위임한 부모, 말을 건 에이전트)의 범위다. inherit_scope 세션만 쓴다."""
        if self._busy:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._idle.wait(), BUSY_GRACE_SEC)
        # 기다린 사이 다른 요청이 먼저 들어갔을 수 있다. 확인과 켜기 사이에 await 가 없어 둘이 함께 통과하지 않는다
        if self._busy:
            raise SessionBusy(BUSY_MESSAGE)
        self._set_busy(True)
        try:
            return await self._prompt(raw_input, credentials or {}, caller_scope)
        except BaseException:
            # run_main 진입 전 실패(검증·인증·rate limit·사고). run_main 의 finally 가 못 끈다.
            self._set_busy(False)
            raise

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self._idle.clear()
        else:
            self._idle.set()

    async def _prompt(
        self, raw_input: str, creds: dict[str, Any], caller_scope: MemoryScope | None
    ) -> AssistantMessage | None:
        # 사용자 활동 기록. idle 트리거가 "조용해진 시점"을 알도록 리셋한다.
        if self._activity_clock is not None:
            self._activity_clock.touch()
        # 사용자가 말했으니 먼저 건넨 말에 대한 대기는 끝났다. 그 말이 먼저 건넨 말에 대한 반응이면 학습한다
        if self._proactivity is not None:
            await self._restore_proactive()
            said, self._awaiting_text = self._awaiting_text, None
            if said is not None:
                task = asyncio.create_task(self._learn_from_reply(said, raw_input))
                self._feedback_tasks.add(task)
                task.add_done_callback(self._feedback_tasks.discard)
            self._proactivity.note_user_activity(self._session_id)
        self._user_spoke = True

        validated, auth_ctx, policy_result = await self._security.run(
            raw_input=raw_input,
            credentials=creds,
            requested_tools=[t.name for t in self._tool_registry.list_all()],
        )

        if policy_result.rate_limit is not None:
            self._check_rate_limit(auth_ctx.user_id, policy_result.rate_limit)

        inherited = caller_scope if self._inherit_scope else None
        self._last_user_id = (inherited.user_id if inherited and inherited.user_id else None) or auth_ctx.user_id

        expanded = self._skill_registry.expand(validated.sanitized)

        history = await self._session_repo.get_messages(self._session_id) if self._needs_history() else []
        route = await self._route(expanded, history)
        frame: ThoughtFrame | None = None
        if route is None:
            frame = None if self._thought_timing == "after" else await self._await_thought(expanded)
        elif route.think:
            self._spawn_routed_thought(expanded)
        self._spawn_loop_judge(expanded, history)
        shown = frame if frame is not None else self._take_pending_frame()
        inner_thought_prompt = self._thought_composer.compose(shown) or None if shown is not None else None
        approval_tools = self._security.sandbox.approval_tools()
        if approval_tools:
            rule = APPROVAL_RULE.format(tools=", ".join(approval_tools))
            inner_thought_prompt = "\n\n".join(p for p in (inner_thought_prompt, rule) if p)
        # 턴 도중 Focus 가 꺼져도 이번 턴은 시작할 때의 훅으로 끝낸다
        hook = self._turn_hook
        if hook is not None:
            addendum = hook.system_addendum()
            inner_thought_prompt = "\n\n".join(p for p in (inner_thought_prompt, addendum) if p) or None
            self._spawn_hook(hook.before_turn(expanded))

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
                    # 플러그인 훅은 Message 로 타입이 잡히지만 받은 AssistantMessage 를 (고쳐) 돌려준다
                    result = cast(AssistantMessage, await self._plugins.emit_on_message_end(result))
                    if hook is not None:
                        self._spawn_hook(hook.after_turn(expanded, result.text()))
                return result
            finally:
                # Dual-Channel 백그라운드 모드에서는 prompt() 가 먼저 돌아오므로 여기서 꺼야 한다.
                self._set_busy(False)

        # Dual-Channel: proactivity가 있으면 needs_background 시 filler 즉시 발화 후
        # 백그라운드 수행(반환 None). 없거나 즉시 모드면 현재 동작 그대로.
        try:
            if self._proactivity is not None:
                return await self._proactivity.dispatch_request(frame, run_main)
            return await run_main()
        finally:
            if route is None and self._thought_timing == "after":
                self._spawn_thought(expanded)

    async def reflect(self) -> ProactiveDecision | None:
        """daemon 자율 성찰(B3). 요청 없이 한 번 성찰해 먼저 말할지 게이팅한다.

        엔진/ proactivity가 없으면 no-op(None). 게이팅 통과 시 core.reflect가
        ProactiveMessageEvent를 push한다.

        외부 이벤트(Phase 3)가 있으면 inbox를 여기서 drain해 사고에 먹인다.
        drain-once이므로 여러 세션이 성찰해도 이벤트당 발화는 1회뿐이다.
        """
        if self._thought_engine is None or self._proactivity is None:
            return None
        await self._restore_proactive()
        # 답을 기다리는 🔔 가 있으면 사고 모델을 부르지 않는다. 외부 이벤트도 꺼내지 않고 남겨 둔다.
        awaiting = self._proactivity.check_awaiting(self._session_id)
        if awaiting is not None:
            self._learn_ignored(awaiting)
            logger.info(f"[Thought] proactive silent: {awaiting.reason}")
            return awaiting
        external_events = self._drain_external_events()
        if not self._user_spoke and not external_events:
            # 앱이나 화면이 새 세션을 열기만 했다. 대화가 없으면 작은 모델은 빈 인사("무엇을 도와드릴까요?")를 건넨다
            return ProactiveDecision(speak=False, reason="no conversation yet")
        loops = [_loop_line(loop) for loop in await self._load_open_loops()]
        if not loops and not external_events:
            # 먼저 말할 근거(챙길 약속, 새 이벤트)가 없다. 사고 모델은 이때 인사나 방금 한 답을 지어 건넸다
            logger.info("[Thought] proactive silent: nothing to tell")
            return ProactiveDecision(speak=False, reason="nothing to tell")
        key = await self._reflect_input_key(loops, external_events)
        if key == self._reflect_key:
            return ProactiveDecision(speak=False, reason="unchanged")
        # 사고 전에 남긴다. 사고가 실패해도 같은 입력으로 30초마다 다시 부르지 않는다
        self._reflect_key = key
        # 사고 기록과 자율 행동은 이 세션의 범위(memory_scope)를 인자로 받는다
        frame = await self._run_inner_thought(
            REFLECTION_SEED,
            mode="reflection",
            external_events=external_events,
        )
        if frame is None:
            return None
        if frame.utterance.strip() and any(same_loop(frame.utterance, said) for said in self._recent_proactive):
            # 최근에 건넨 말을 사고 프롬프트에 보여 줘도 같은 말을 다시 고른다. 같은 🔔 와 피드백 질문이 반복된다
            logger.info("[Thought] proactive silent: repeats a recent proactive message")
            return ProactiveDecision(speak=False, reason="repeat")
        if frame.utterance.strip() and refers_to(frame.utterance, await self._recent_answer(time.time() * 1000)):
            # 사고는 방금 끝난 답("가장 추천하는 공고는…")을 말만 바꿔 알릴 거리로 다시 고르곤 한다
            logger.info("[Thought] proactive silent: repeats the last answer")
            return ProactiveDecision(speak=False, reason="repeat")
        decision = await self._proactivity.reflect(
            frame, session_id=self._session_id, execute=self._execute_autonomous
        )
        self._learn_ignored(decision)
        if not decision.speak:
            # 🔔 가 안 뜨는 이유(임계치 미달, 쿨다운, utterance 비움)를 로그에서 볼 수 있게.
            logger.info(f"[Thought] proactive silent: {decision.reason}")
        return decision

    async def _reflect_input_key(self, loops: list[str], external_events: list[str]) -> tuple[Any, ...]:
        """성찰 입력이 같은지 가르는 키. 마지막 메시지, 약속, 이벤트, 그리고 REFLECT_REFRESH_SEC 단위 시각."""
        messages = await self._session_repo.get_messages(self._session_id)
        last = messages[-1].timestamp if messages else 0
        return (last, tuple(loops), tuple(external_events), int(time.time() // REFLECT_REFRESH_SEC))

    async def _learn_from_reply(self, said: str, reply: str) -> None:
        """먼저 건넨 말 뒤 첫 말로 학습한다. 받아들이면 수락, 거절하거나 미루면 무시, 딴 얘기면 약한 무시."""
        if self._reply_classifier is None:
            return
        verdict = await self._reply_classifier.classify("feedback", reply, said)
        if verdict in ("accept", "dismiss"):
            await self.record_feedback(verdict == "accept")
        elif self._feedback_learner is not None:
            self._feedback_learner.record_ignored()
        logger.info(f"[Proactive] reply to proactive: {verdict}")

    async def _recent_answer(self, now_ms: float) -> str:
        """REPEAT_ANSWER_SEC 안에 한 마지막 답. 그보다 오래된 답의 기한을 다시 알리는 🔔 는 막지 않는다."""
        # ponytail: 마지막 답 하나만 본다, 🔔 가 그 앞 답을 되풀이하는 일이 보이면 최근 몇 개로 넓힌다
        messages = await self._session_repo.get_messages(self._session_id)
        answer = next((m for m in reversed(messages) if isinstance(m, AssistantMessage) and m.text().strip()), None)
        if answer is None or now_ms - answer.timestamp > REPEAT_ANSWER_SEC * 1000:
            return ""
        return answer.text()

    def _learn_ignored(self, decision: ProactiveDecision) -> None:
        # 게이트는 발화 하나당 한 번만 ignored 를 세우므로 여기서 중복 기록되지 않는다
        if decision.ignored and self._feedback_learner is not None:
            self._feedback_learner.record_ignored()
            logger.info("[Thought] proactive ignored: 답 없이 지나 약한 무시로 기록")

    async def _execute_autonomous(self, actions: list[ProactiveAction]) -> str:
        """저위험 자율 행동(E2)을 실행하고 사람이 읽을 요약을 반환.

        이중 안전 게이트: (1) AUTONOMOUS_SAFE_TOOLS 화이트리스트 ∩
        (2) sandbox 승인 불필요. 둘 다 통과한 tool 행동만 실행한다(고위험·외부
        변경·승인 대상은 절대 자율 실행하지 않음. 요청 없는 시점엔 승인 주체 없음).
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
                from jarvis.core.tools.registry import ToolContext

                context = ToolContext(scope=self.memory_scope, session_id=self._session_id, user_id=self._last_user_id)
                result = await self._tool_registry.execute(call_id, action.tool_name, action.args, context=context)
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

        inbox가 없으면(소스 미설정) 빈 목록. 기존 동작과 완전히 동일하다.
        external_detail_in_prompt=False(기본)면 원문 대신 제목만 싣는다.
        메일 본문 등이 사고 로그·LTM에 축적되는 것을 막는다.
        """
        if self._external_inbox is None:
            return []
        return [
            event.as_line(include_detail=self._external_detail_in_prompt)
            for event in self._external_inbox.drain()
        ]

    def set_turn_hook(self, hook: TurnHook | None) -> None:
        """턴 훅을 끼우거나(None 이면) 뺀다. 같은 훅을 두 번 끼워도 하나다."""
        self._turn_hook = hook

    @property
    def turn_hook(self) -> TurnHook | None:
        return self._turn_hook

    async def emit(self, event: AgentEvent) -> None:
        """턴 바깥에서 이 세션의 구독자(열린 화면)에게 이벤트를 보낸다."""
        await self._harness.emit_event(event)

    def _spawn_hook(self, coro: Awaitable[None]) -> None:
        task = asyncio.ensure_future(coro)
        self._hook_tasks.add(task)
        task.add_done_callback(self._on_hook_done)

    def _on_hook_done(self, task: asyncio.Task[Any]) -> None:
        self._hook_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.info(f"[Focus] turn hook failed: {task.exception()!r}")

    def _needs_history(self) -> bool:
        return self._thought_router is not None or (self._loop_judge is not None and self._openloop_store is not None)

    async def _route(self, user_input: str, history: list[Any]) -> RouteVerdict | None:
        """router 가 없거나 사고 엔진이 없으면 None(예전 request_timing 동작)."""
        if self._thought_router is None or self._thought_engine is None:
            return None
        verdict = await self._thought_router.route(user_input, history)
        p = f"{verdict.p_think:.3f}" if verdict.p_think is not None else "none"
        logger.info(f"[Router] p_think={p} → {'think' if verdict.think else 'direct'}")
        await self._harness.emit_event(
            ThoughtRouteEvent(session_id=self._session_id, think=verdict.think, p_think=verdict.p_think)
        )
        return verdict

    def _take_pending_frame(self) -> ThoughtFrame | None:
        """앞 턴에 응답과 함께 돈 사고의 결과. 한 번 넣으면 비워 같은 사고가 두 번 들어가지 않는다."""
        frame, self._pending_frame = self._pending_frame, None
        return frame

    def _spawn_routed_thought(self, user_input: str) -> None:
        task = asyncio.create_task(self._routed_thought(user_input))
        self._late_thoughts.add(task)
        task.add_done_callback(self._on_thought_done)

    async def _routed_thought(self, user_input: str) -> None:
        frame: ThoughtFrame | None = None
        try:
            frame = await self._run_inner_thought(user_input)
            if frame is not None:
                self._pending_frame = frame
        finally:
            await self._harness.emit_event(ThoughtEndEvent(session_id=self._session_id, ok=frame is not None))

    def _spawn_loop_judge(self, user_input: str, history: list[Any]) -> None:
        if self._loop_judge is None or self._openloop_store is None:
            return
        task = asyncio.create_task(self._judge_open_loops(user_input, history))
        self._loop_tasks.add(task)
        task.add_done_callback(self._on_loop_judge_done)

    def _on_loop_judge_done(self, task: asyncio.Task[Any]) -> None:
        self._loop_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.info(f"[Agenda] judge failed: {task.exception()!r}")

    async def _judge_open_loops(self, user_input: str, history: list[Any]) -> None:
        """AGENDA 판단 한 번: 사용자 입력으로 끝난 약속을 닫고 새 약속을 연다."""
        assert self._loop_judge is not None
        shown = await self._load_open_loops()
        verdict = await self._loop_judge.judge(
            user_input, [f"[{i}] {_loop_line(loop)}" for i, loop in enumerate(shown, 1)], history
        )
        if verdict is None:
            return
        closed = await self._close_open_loops(verdict.closed_loops, shown, user_input)
        opened = await self._persist_open_loops(verdict.open_loops, verdict.closed_loops, user_input)
        if closed or opened:
            await self._harness.emit_event(AgendaChangedEvent(session_id=self._session_id))

    async def settle(self) -> None:
        """응답과 함께 띄운 사고와 AGENDA 판단이 끝날 때까지 기다린다. 세션 저장과 테스트가 쓴다."""
        await asyncio.gather(*self._late_thoughts, *self._loop_tasks, return_exceptions=True)

    def _spawn_thought(self, user_input: str) -> asyncio.Task[Any] | None:
        """사고를 뒤에서 돌린다. 끝나면 _run_inner_thought 가 기록과 이벤트를 알아서 남긴다."""
        if self._thought_engine is None:
            return None
        task = asyncio.create_task(self._run_inner_thought(user_input))
        self._late_thoughts.add(task)
        task.add_done_callback(self._on_thought_done)
        return task

    async def _await_thought(self, user_input: str) -> ThoughtFrame | None:
        """before 면 끝까지, race 면 wait_sec 까지만 기다린다. 늦으면 메인 응답을 먼저 시작한다."""
        if self._thought_engine is None:
            return None
        if self._thought_timing == "before":
            return await self._run_inner_thought(user_input)
        task = self._spawn_thought(user_input)
        assert task is not None
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=self._thought_wait_sec)
        except TimeoutError:
            logger.info(f"[Thought] request frame late (>{self._thought_wait_sec}s): main turn starts without it")
            return None

    def _on_thought_done(self, task: asyncio.Task[Any]) -> None:
        self._late_thoughts.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.info(f"[Thought] request thought failed: {task.exception()!r}")

    async def _run_inner_thought(
        self,
        user_input: str,
        mode: ThoughtMode = "request",
        external_events: list[str] | None = None,
    ) -> ThoughtFrame | None:
        """메타인지 1회. 요청 시점(expand 직후) 또는 daemon 성찰(mode="reflection").

        사고 프레임을 생성·기록·이벤트로 노출하고 그 프레임을 반환한다. 프레임은
        ① composer 조립(컨텍스트 증강)과 ② proactivity 판단에 쓰인다.
        엔진이 없거나(비활성) 사고가 생략/실패하면 None을 돌려 메인 턴을 그대로 진행.
        """
        if self._thought_engine is None:
            return None

        shown_loops = await self._load_open_loops()
        frame = await self._thought_engine.think(
            ThoughtRequest(
                user_input=user_input,
                history=await self._session_repo.get_messages(self._session_id),
                session_id=self._session_id,
                user_id=self.memory_scope.user_id,
                agent_id=self.memory_scope.agent_id,
                open_loops=[f"[{i}] {_loop_line(loop)}" for i, loop in enumerate(shown_loops, 1)],
                user_model=await self._load_user_model(),
                external_events=external_events or [],
                recent_proactive=list(self._recent_proactive),
                mode=mode,
            )
        )
        if frame is None:
            return None

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
            await self._thought_log.store(frame, self.memory_scope)

        return frame

    async def _emit_proactive(self, message: ProactiveMessage) -> None:
        """ProactivityCore의 push 콜백. ProactiveMessage → ProactiveMessageEvent."""
        # Focus 같은 턴 훅이 붙어 있으면 먼저 거는 말은 집중을 깨므로 내지 않는다. filler, 맡긴 일의 답은 보낸다
        if message.kind == "proactive" and self._turn_hook is not None:
            logger.info(f"[Proactive] suppressed during turn hook: {message.text[:40]}")
            return
        # 답하는 중에 먼저 거는 말은 그 답과 엇갈린다(공고 계산 중에 "조건을 말해 주세요"). 끝난 뒤 성찰이 다시 본다
        if message.kind == "proactive" and self._busy:
            logger.info(f"[Proactive] suppressed while answering: {message.text[:40]}")
            return
        if message.kind == "proactive":
            self._recent_proactive.append(message.text)
            self._last_proactive_id = message.id
            self._awaiting_text = message.text
            # 내보내기 전에 남긴다. 남긴 뒤 죽으면 재시작 뒤 게이트가 닫혀 있어 같은 말을 다시 하지 않는다
            try:
                await self._session_repo.append_proactive(self._session_id, message.id, message.text)
                # 먼저 건넨 말도 대화의 한 턴이다. 기록에 있어야 뒤이은 "응, 해줘" 를 메인 모델이 알아듣는다
                await self._session_repo.append(
                    self._session_id, AssistantMessage(content=[TextContent(text=message.text)])
                )
            except Exception as exc:
                logger.warning(f"[Proactive] not saved, a restart may repeat it: {exc!r}")
        await self._harness.emit_event(
            ProactiveMessageEvent(
                session_id=self._session_id,
                text=message.text,
                kind=message.kind,
                message_id=message.id,
            )
        )

    async def _restore_proactive(self) -> None:
        """재시작 전에 먼저 건넨 말과 그 말의 응답 대기를 되살린다. 세션당 한 번만 읽는다."""
        if self._proactive_restored or self._proactivity is None:
            return
        self._proactive_restored = True
        try:
            said = await self._session_repo.get_proactive(self._session_id)
            acks = await self._session_repo.get_proactive(self._session_id, PROACTIVE_ACK_ENTRY)
            messages = await self._session_repo.get_messages(self._session_id)
        except Exception as exc:
            logger.warning(f"[Proactive] restore failed: {exc!r}")
            return
        self._recent_proactive.extend(e.content.get("text", "") for e in said)
        self._user_spoke = self._user_spoke or any(isinstance(m, UserMessage) for m in messages)
        if not said:
            return
        last = said[-1]
        self._last_proactive_id = last.id
        # 사용자가 말했거나 피드백을 줬으면 그 🔔 의 대기는 끝났다
        last_user = max((m.timestamp for m in messages if isinstance(m, UserMessage)), default=0)
        released = max(last_user, max((a.timestamp for a in acks), default=0))
        if last.timestamp > released:
            self._proactivity.restore_awaiting(self._session_id)
            self._awaiting_text = last.content.get("text") or None
        self._proactivity.restore_last_spoke(self._session_id, (time.time() * 1000 - last.timestamp) / 1000)

    async def record_feedback(self, accepted: bool) -> None:
        """proactive 발화에 대한 사용자 피드백(수락/무시)을 학습기에 기록 (C3).

        채널 무관(web 버튼 / TUI 키 / voice). UI가 이 진입점으로 신호를 모은다.
        """
        if self._feedback_learner is not None:
            self._feedback_learner.record(accepted)
        # 화면이 따로 피드백을 보냈으면 다음 말로 다시 학습하지 않는다
        self._awaiting_text = None
        if self._proactivity is not None:
            await self._restore_proactive()
            self._proactivity.note_user_activity(self._session_id)
            if self._last_proactive_id is not None:
                # 재시작 뒤에도 이 🔔 에는 답을 받았다고 본다. 같은 🔔 의 피드백은 몇 번 와도 하나다
                with contextlib.suppress(Exception):
                    await self._session_repo.append_proactive(
                        self._session_id, f"ack-{self._last_proactive_id}", "", PROACTIVE_ACK_ENTRY
                    )

    async def _load_open_loops(self) -> list[OpenLoop]:
        """기한이 지난 약속을 닫은 뒤 사고에 보여줄 열린 open-loop(store 미설정이면 빈 목록)."""
        if self._openloop_store is None:
            return []
        try:
            if self._openloop_expiry is not None:
                await close_expired(
                    self._openloop_store,
                    now_ms=int(time.time() * 1000),
                    grace_ms=self._openloop_expiry.grace_ms,
                    max_age_ms=self._openloop_expiry.max_age_ms,
                    session_id=self._session_id,
                )
            return await self._openloop_store.list_open(session_id=self._session_id)
        except Exception:
            return []

    async def _load_user_model(self) -> str:
        """증류된 사용자 모델을 사고 컨텍스트 블록으로 주입(없으면 빈 문자열)."""
        if self._user_model_store is None:
            return ""
        try:
            model = await self._user_model_store.get()
        except Exception:
            return ""
        return model.as_context() if model is not None else ""

    async def _close_open_loops(self, closed: list[str], shown: list[OpenLoop], user_input: str) -> bool:
        """AGENDA 판단이 닫으라고 짚은 약속(보여준 번호 또는 문구)은 done, 사용자가 거둔 약속은 dismissed 로 닫는다.
        두 번 닫아도 결과는 같다. 하나라도 닫았으면 True."""
        if self._openloop_store is None:
            return False
        done = matching_ids(shown, closed)
        dropped = [i for i in cancelled_ids(shown, user_input) if i not in done]
        changed = False
        with contextlib.suppress(Exception):
            for loop_id in done:
                changed = await self._openloop_store.update_status(loop_id, "done") or changed
            for loop_id in dropped:
                changed = await self._openloop_store.update_status(loop_id, "dismissed") or changed
        return changed

    async def _persist_open_loops(self, opened: list[str], closed: list[str], user_input: str) -> bool:
        """AGENDA 판단이 새로 감지한 open-loop를 저장(같은 약속이면 store가 기한만 갱신). 부가 작업이라 실패 무시.
        새로 열거나 기한을 바꿨으면 True."""
        if self._openloop_store is None or not opened:
            return False
        changed = False
        for note in opened:
            note, evidence = split_evidence(note)
            text, due_ms = parse_loop_note(note)
            # 작은 모델은 취소하는 턴에 그 약속을 open_loops 에도 적는다. 같은 프레임에서 닫으라고 한 건 열지 않는다
            if not text or not grounded(text, user_input, evidence):
                continue
            if any(refers_to(c, text) for c in closed):
                continue
            with contextlib.suppress(Exception):
                loop_id = await self._openloop_store.add_unique(
                    OpenLoop(
                        description=text,
                        due_ms=due_ms,
                        origin_session=self._session_id,
                        agent_id=self.memory_scope.agent_id,
                    )
                )
                changed = changed or loop_id is not None
        return changed

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

    def register_tool(self, tool: JarvisTool) -> None:
        """세션 생성 뒤 도구를 더한다. harness 가 생성 시점 스냅샷을 쓰므로 LLM 도구 목록도 갱신한다."""
        self._tool_registry.register(tool)
        self._harness._tools = self._tool_registry.to_llm_tools()

    @property
    def session_id(self) -> str:
        return self._session_id

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

    def _make_tool_executor(self, auth_ctx: AuthContext, policy_result: PolicyResult) -> ToolExecutor:
        allowed = policy_result.allowed_tools

        async def executor(tool_call_id: str, tool_name: str, params: dict[str, Any]) -> ToolResultMessage:
            if "*" not in allowed and tool_name not in allowed:
                from jarvis.model_layer.types import TextContent

                return ToolResultMessage(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    content=[TextContent(text=f"Tool '{tool_name}' is not permitted for this user")],
                    is_error=True,
                )

            hook_result = await self._plugins.emit_before_tool_call(tool_name, params, auth_ctx)
            if hook_result and hook_result.get("block"):
                from jarvis.model_layer.types import TextContent

                return ToolResultMessage(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    content=[TextContent(text=hook_result.get("reason", "Blocked by plugin"))],
                    is_error=True,
                )

            decision = await self._security.sandbox.decide(tool_name, params)
            if decision != "allow":
                from jarvis.model_layer.types import TextContent

                return ToolResultMessage(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    content=[TextContent(text=DENIED_RESULT[decision].format(tool=tool_name) + DENIED_RESULT_TAIL)],
                    is_error=True,
                    denied=True,
                    timed_out=decision == "timeout",
                )

            from jarvis.core.tools.registry import ToolContext

            context = ToolContext(
                scope=self.memory_scope, session_id=self._session_id, user_id=self._last_user_id, call=executor
            )
            result = await self._tool_registry.execute(tool_call_id, tool_name, params, context=context)
            await self._plugins.emit_after_tool_call(tool_name, params, {"is_error": result.is_error})
            return result

        return executor


def _loop_line(loop: OpenLoop) -> str:
    """사고에 보여줄 약속 한 줄. 기한은 [지금]과 같은 로컬 시각으로 붙인다."""
    if loop.due_ms is None:
        return loop.description
    due = datetime.fromtimestamp(loop.due_ms / 1000).strftime("%Y-%m-%d %H:%M")
    return f"{loop.description} (기한 {due})"
