from __future__ import annotations

import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.agent_layer.harness import AgentHarness
from jarvis.agent_layer.memory.chain import MemoryMiddlewareChain
from jarvis.agent_layer.session.protocol import SessionRepo
from jarvis.agent_layer.thought import (
    DefaultThoughtComposer,
    ThoughtComposer,
    ThoughtEngine,
    ThoughtLog,
    ThoughtRequest,
)
from jarvis.agent_layer.types import AgentEvent, AgentLoopConfig, InnerThoughtEvent
from jarvis.core.plugins.runner import PluginRunner
from jarvis.core.policy.pipeline import AuthContext, PolicyDenied, PolicyResult, SecurityPipeline
from jarvis.core.skills.registry import SkillRegistry
from jarvis.core.tools.registry import ToolRegistry
from jarvis.model_layer.types import AssistantMessage, ModelConfig

AgentEventSink = Callable[[AgentEvent], Awaitable[None]]


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
    ) -> None:
        self._security = security_pipeline
        self._plugins = plugin_runner
        self._tool_registry = tool_registry
        self._skill_registry = skill_registry
        self._session_id = session_id
        self._session_repo = session_repo
        self._memory_chain = memory_chain
        self._thought_engine = thought_engine
        self._thought_log = thought_log
        self._thought_composer = thought_composer or DefaultThoughtComposer()

        self._rate_counters: dict[str, deque[float]] = {}

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
        creds = credentials or {}

        validated, auth_ctx, policy_result = await self._security.run(
            raw_input=raw_input,
            credentials=creds,
            requested_tools=self._tool_registry.list_all() and
                [t.name for t in self._tool_registry.list_all()],
        )

        if policy_result.rate_limit is not None:
            self._check_rate_limit(auth_ctx.user_id, policy_result.rate_limit)

        expanded = self._skill_registry.expand(validated.sanitized)

        inner_thought_prompt = await self._run_inner_thought(expanded)

        await self._plugins.emit_before_agent_start(expanded, {"session_id": self._session_id})

        tool_executor = self._make_tool_executor(auth_ctx, policy_result)

        result = await self._harness.run(
            user_input=expanded,
            tool_executor=tool_executor,
            extra_context={
                "user_id": auth_ctx.user_id,
                "roles": list(auth_ctx.roles),
                "inner_thought_prompt": inner_thought_prompt,
            },
        )

        if result:
            result = await self._plugins.emit_on_message_end(result)

        return result

    async def _run_inner_thought(self, user_input: str) -> str | None:
        """
        요청 시점 메타인지 — expand 직후, harness.run 직전에 실행.

        Tier 0: 사고 프레임을 생성·기록·이벤트로 노출하고, composer로 조립한
        프롬프트 텍스트를 반환한다(자율 행동 없음). 엔진이 없거나(비활성) 사고가
        생략/실패하면 조용히 None을 돌려 메인 턴을 그대로 진행한다.
        """
        if self._thought_engine is None:
            return None

        frame = await self._thought_engine.think(
            ThoughtRequest(
                user_input=user_input,
                history=await self._session_repo.get_messages(self._session_id),
                session_id=self._session_id,
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
            await self._thought_log.store(frame, self._session_id)

        return self._thought_composer.compose(frame) or None

    def _check_rate_limit(self, user_id: str, rate_limit: int, window: float = 60.0) -> None:
        """슬라이딩 윈도우(window초)에서 rate_limit 초과 시 PolicyDenied."""
        now = time.monotonic()
        if user_id not in self._rate_counters:
            self._rate_counters[user_id] = deque()
        timestamps = self._rate_counters[user_id]
        while timestamps and now - timestamps[0] > window:
            timestamps.popleft()
        if len(timestamps) >= rate_limit:
            raise PolicyDenied(
                f"Rate limit exceeded: {rate_limit} requests/{int(window)}s for user '{user_id}'"
            )
        timestamps.append(now)

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
        return self._harness.is_running

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

            if self._security.sandbox.is_approval_required(tool_name):
                approved = await self._security.sandbox.request_approval(
                    command=str(params),
                    reason=f"Tool '{tool_name}' requires approval",
                )
                if not approved:
                    from jarvis.model_layer.types import TextContent, ToolResultMessage
                    return ToolResultMessage(
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        content=[TextContent(text=f"Execution of '{tool_name}' was denied")],
                        is_error=True,
                    )

            result = await self._tool_registry.execute(tool_call_id, tool_name, params)
            await self._plugins.emit_after_tool_call(tool_name, params, {"is_error": result.is_error})
            return result

        return executor
