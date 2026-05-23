from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.agent_layer.loop import AgentEventSink, run_agent_loop
from jarvis.agent_layer.memory.chain import MemoryMiddlewareChain
from jarvis.agent_layer.session.protocol import SessionRepo
from jarvis.agent_layer.types import AgentContext, AgentEvent, AgentLoopConfig
from jarvis.model_layer.types import AssistantMessage, ModelConfig, Tool, ToolResultMessage


class AgentHarness:
    """
    Agent 실행의 stateful 래퍼.
    메모리 미들웨어 적용, 세션 영속성, 이벤트 구독 관리.
    Pi: AgentHarness 패턴.
    """

    def __init__(
        self,
        model: ModelConfig,
        session_id: str,
        memory_chain: MemoryMiddlewareChain,
        session_repo: SessionRepo,
        system_prompt: str | None = None,
        tools: list[Tool] | None = None,
        loop_config: AgentLoopConfig | None = None,
        agent_name: str | None = None,
    ) -> None:
        self._model = model
        self._session_id = session_id
        self._memory_chain = memory_chain
        self._session_repo = session_repo
        self._system_prompt = system_prompt
        self._tools: list[Tool] = tools or []
        self._loop_config = loop_config or AgentLoopConfig()
        self._listeners: list[AgentEventSink] = []
        self._signal = asyncio.Event()
        self._running = False
        self._agent_name: str | None = agent_name

    def subscribe(self, listener: AgentEventSink) -> Callable[[], None]:
        self._listeners.append(listener)
        def unsubscribe():
            self._listeners.remove(listener)
        return unsubscribe

    async def _emit(self, event: AgentEvent) -> None:
        await asyncio.gather(*[fn(event) for fn in self._listeners], return_exceptions=True)

    async def run(
        self,
        user_input: str,
        tool_executor: Callable[[str, str, dict[str, Any]], Awaitable[ToolResultMessage]] | None = None,
        extra_context: dict[str, Any] | None = None,
    ) -> AssistantMessage | None:
        from jarvis.model_layer.types import UserMessage

        self._running = True
        self._signal.clear()

        history = await self._session_repo.get_messages(self._session_id)
        new_user_msg = UserMessage(content=user_input)
        history.append(new_user_msg)
        await self._session_repo.append(self._session_id, new_user_msg)

        mem_context: dict[str, Any] = {
            "session_id": self._session_id,
            **(extra_context or {}),
        }
        messages = await self._memory_chain.transform(history, mem_context)

        agent_context = AgentContext(
            session_id=self._session_id,
            messages=messages,
            tools=self._tools,
            model=self._model,
            system_prompt=self._system_prompt,
            metadata=extra_context or {},
        )

        result = await run_agent_loop(
            context=agent_context,
            config=self._loop_config,
            emit=self._emit,
            tool_executor=tool_executor,
            signal=self._signal,
            agent_name=self._agent_name,
        )

        if result:
            await self._session_repo.append(self._session_id, result)
            await self._memory_chain.store(result, mem_context)

        self._running = False
        return result

    def abort(self) -> None:
        self._signal.set()

    @property
    def is_running(self) -> bool:
        return self._running
