"""[app] SubagentBuilder: 에이전트 정의 파일의 서브 에이전트 세션과 위임 도구를 조립한다."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.core.multi_agent.factory import AgentDefinition, AgentFactory
    from jarvis.core.multi_agent.tool import AgentNodeTool
    from jarvis.core.tools.registry import ToolRegistry
    from jarvis.app.app_services import AppServices
    from jarvis.app.app_context import AppContext
    from jarvis.core.session import AgentSession


class SubagentBuilder:
    """AgentFactory 가 위임 시점에 부르는 (정의, 세션 id) → 격리된 AgentSession 빌더."""

    def __init__(self, ctx: "AppContext", services: "AppServices", main_registry: "ToolRegistry") -> None:
        self._ctx = ctx
        self._services = services
        self._main_registry = main_registry

    def build_session(self, definition: "AgentDefinition", session_id: str) -> "AgentSession":
        """메모리는 부모의 사용자를 이어받고 에이전트 id 는 자기 이름(inherit_scope). 도구는 정의에 적힌 것만
        (비어 있으면 메인 전체). 호출 시점에 고르므로 나중에 등록된 도구(다른 에이전트, orchestrate)도 보인다."""
        from jarvis.core.tools.registry import ToolRegistry
        from jarvis.model_layer.types import ModelConfig
        from jarvis.core.session import AgentSession

        settings = self._ctx.settings
        if definition.model_override:
            model = ModelConfig(
                provider=settings.llm.provider,
                model=definition.model_override,
                api_key=settings.llm.api_key.get_secret_value() if settings.llm.api_key else None,
                base_url=settings.llm.base_url,
                temperature=settings.llm.temperature,
                max_tokens=settings.llm.max_tokens,
            )
        else:
            model = self._services.model_config
        if definition.tools or definition.tools_only:
            registry = ToolRegistry()
            for tool_name in definition.tools:
                tool = self._main_registry.get(tool_name)
                if tool is not None:
                    registry.register(tool)
        else:
            registry = self._main_registry
        return AgentSession(
            model=model,
            session_id=session_id,
            security_pipeline=self._services.pipeline,
            plugin_runner=self._services.plugin_runner,
            memory=self._services.memory,
            tool_registry=registry,
            skill_registry=self._services.skill_registry,
            session_repo=self._ctx.session_repo,
            system_prompt=definition.system_prompt,
            agent_name=definition.name,
            inherit_scope=True,
        )

    def node_tool(self, definition: "AgentDefinition", factory: "AgentFactory") -> "AgentNodeTool":
        """정의 → 지연 생성 노드를 감싼 위임 도구. 세션은 첫 위임 때 factory 가 만든다."""
        from jarvis.core.multi_agent.tool import AgentNodeTool

        tool = AgentNodeTool(definition=definition, factory=factory, memory=self._services.memory)
        # 정의의 설명을 LLM 이 읽는 도구 설명으로 쓴다
        if definition.description:
            tool.description = definition.description
        return tool
