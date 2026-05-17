from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from jarvis.agent_layer.harness import AgentHarness
from jarvis.agent_layer.memory.chain import MemoryMiddlewareChain
from jarvis.agent_layer.session.protocol import SessionRepo
from jarvis.agent_layer.types import AgentEvent, AgentLoopConfig
from jarvis.core.plugins.runner import PluginRunner
from jarvis.core.policy.pipeline import AuthContext, PolicyResult, SecurityPipeline
from jarvis.core.skills.registry import SkillRegistry
from jarvis.core.tools.registry import ToolRegistry
from jarvis.model_layer.types import AssistantMessage, ModelConfig, Tool


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
    ) -> None:
        self._security = security_pipeline
        self._plugins = plugin_runner
        self._tool_registry = tool_registry
        self._skill_registry = skill_registry
        self._session_id = session_id

        self._harness = AgentHarness(
            model=model,
            session_id=session_id,
            memory_chain=memory_chain,
            session_repo=session_repo,
            system_prompt=system_prompt,
            tools=tool_registry.to_llm_tools(),
            loop_config=loop_config,
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

        expanded = self._skill_registry.expand(validated.sanitized)

        await self._plugins.emit_before_agent_start(expanded, {"session_id": self._session_id})

        tool_executor = self._make_tool_executor(auth_ctx, policy_result)

        result = await self._harness.run(
            user_input=expanded,
            tool_executor=tool_executor,
            extra_context={
                "user_id": auth_ctx.user_id,
                "roles": list(auth_ctx.roles),
            },
        )

        if result:
            result = await self._plugins.emit_on_message_end(result)

        return result

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
