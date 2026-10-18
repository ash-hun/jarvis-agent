"""승인이 필요한 도구: 모델이 방법 안내로 피하지 않게 규칙을 덧붙이고, 거부 결과는 도구를 계속 쓸 수 있다고 알린다."""

from typing import Any
from collections.abc import AsyncIterator

from jarvis.model_layer.types import LLMContext, ModelConfig, StreamEvent, StreamOptions
from jarvis.model_layer.registry import get_default_registry
from tests.fixtures.faux_provider import FauxProvider


class _Recording(FauxProvider):
    def __init__(self) -> None:
        super().__init__(response="네")
        self.system_prompts: list[str | None] = []

    async def stream(
        self, model: ModelConfig, context: LLMContext, options: StreamOptions | None = None
    ) -> AsyncIterator[StreamEvent]:
        self.system_prompts.append(context.system_prompt)
        async for event in super().stream(model, context, options):
            yield event


def _pipeline(sandbox: Any) -> Any:
    from jarvis.core.policy.authenticator import NoAuthAuthenticator
    from jarvis.core.policy.validator import DefaultInputValidator
    from jarvis.core.policy.pipeline import SecurityPipeline
    from jarvis.core.policy.policy import AllowAllPolicy

    return SecurityPipeline(
        validator=DefaultInputValidator(), authenticator=NoAuthAuthenticator(), policy=AllowAllPolicy(), sandbox=sandbox
    )


def _session(pipeline: Any, fx: dict[str, Any]) -> Any:
    from jarvis.core.session import AgentSession

    return AgentSession(
        model=ModelConfig(provider="faux", model="faux-model"),
        session_id="approval-rule",
        security_pipeline=pipeline,
        plugin_runner=fx["plugin_runner"],
        memory=fx["session_memory"],
        tool_registry=fx["tool_registry"],
        skill_registry=fx["skill_registry"],
        session_repo=fx["repo"],
    )


async def test_rule_lists_approval_tools_and_denial_keeps_tool_usable(
    monkeypatch, plugin_runner, session_memory, tool_registry, skill_registry, jsonl_repo
) -> None:
    from jarvis.core.policy.pipeline import AuthContext, PolicyResult
    from jarvis.core.policy.sandbox import DefaultSandbox

    async def deny(command: str, reason: str, always_pattern: str = "") -> bool:
        return False

    provider = _Recording()
    monkeypatch.setitem(get_default_registry()._providers, "faux", provider)
    sandbox = DefaultSandbox(require_approval_for=["bash"])
    sandbox.set_approval_callback(deny)
    fx = {
        "plugin_runner": plugin_runner,
        "session_memory": session_memory,
        "tool_registry": tool_registry,
        "skill_registry": skill_registry,
        "repo": jsonl_repo,
    }
    await jsonl_repo.create(session_id="approval-rule")
    session = _session(_pipeline(sandbox), fx)

    await session.prompt("권한을 바꿔 줘")
    assert "[도구 승인] bash 는 실행 전에 시스템이 사용자에게 승인을 묻는다" in (provider.system_prompts[-1] or "")

    auth = AuthContext(user_id="local", roles=frozenset())
    policy = PolicyResult(allowed_tools=frozenset({"*"}), allowed_skills=frozenset())
    executor = session._make_tool_executor(auth, policy)
    result = await executor("call-1", "bash", {"command": "chmod 000 a.md"})
    assert result.is_error
    assert "도구는 계속 쓸 수 있다" in result.content[0].text


async def test_no_rule_without_approval_tools(
    monkeypatch, permissive_pipeline, plugin_runner, session_memory, tool_registry, skill_registry, jsonl_repo
) -> None:
    provider = _Recording()
    monkeypatch.setitem(get_default_registry()._providers, "faux", provider)
    fx = {
        "plugin_runner": plugin_runner,
        "session_memory": session_memory,
        "tool_registry": tool_registry,
        "skill_registry": skill_registry,
        "repo": jsonl_repo,
    }
    await jsonl_repo.create(session_id="approval-rule")
    await _session(permissive_pipeline, fx).prompt("안녕")
    assert "[도구 승인]" not in (provider.system_prompts[-1] or "")
