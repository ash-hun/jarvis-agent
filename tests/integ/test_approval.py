"""approval 기능: 승인 도구가 있으면 세션 프롬프트에 규칙을 붙이고, 거부 결과가 도구를 다시 쓸 수 있다고 알린다."""

from typing import Any

from tests.fixtures.agent_loop_helpers import ScriptedProvider, register, text_turn, tool_turn
from jarvis.core.policy.authenticator import NoAuthAuthenticator
from jarvis.core.policy.validator import DefaultInputValidator
from jarvis.model_layer.model_types import ToolResultMessage
from jarvis.core.policy.pipeline import SecurityPipeline
from jarvis.core.policy.sandbox import DefaultSandbox
from jarvis.core.policy.policy import AllowAllPolicy
from jarvis.core.session import AgentSession

APPROVAL_RULE_HEAD = "[도구 승인] bash 는 실행 전에 시스템이 사용자에게 승인을 묻는다"


def _session(provider: ScriptedProvider, pipeline: SecurityPipeline, fx: dict[str, Any]) -> AgentSession:
    return AgentSession(
        model=register(provider),
        session_id="approval-rule",
        security_pipeline=pipeline,
        plugin_runner=fx["plugin_runner"],
        memory=fx["session_memory"],
        tool_registry=fx["tool_registry"],
        skill_registry=fx["skill_registry"],
        session_repo=fx["repo"],
    )


async def test_rule_lists_approval_tools_and_denial_keeps_tool_usable(
    plugin_runner, session_memory, tool_registry, skill_registry, jsonl_repo
) -> None:
    async def deny(command: str, reason: str, always_pattern: str = "") -> bool:
        return False

    sandbox = DefaultSandbox(require_approval_for=["bash"])
    sandbox.set_approval_callback(deny)
    pipeline = SecurityPipeline(
        validator=DefaultInputValidator(), authenticator=NoAuthAuthenticator(), policy=AllowAllPolicy(), sandbox=sandbox
    )
    provider = ScriptedProvider([tool_turn(("call-1", "bash", {"command": "chmod 000 a.md"})), text_turn("네")])
    fx = {"plugin_runner": plugin_runner, "session_memory": session_memory, "tool_registry": tool_registry,
          "skill_registry": skill_registry, "repo": jsonl_repo}
    await jsonl_repo.create(session_id="approval-rule")

    await _session(provider, pipeline, fx).prompt("권한을 바꿔 줘")

    assert APPROVAL_RULE_HEAD in (provider.calls[-1].system_prompt or "")
    result = next(m for m in await jsonl_repo.get_messages("approval-rule") if isinstance(m, ToolResultMessage))
    assert result.is_error
    assert "도구는 계속 쓸 수 있다" in result.content[0].text


async def test_no_rule_without_approval_tools(
    permissive_pipeline, plugin_runner, session_memory, tool_registry, skill_registry, jsonl_repo
) -> None:
    provider = ScriptedProvider([text_turn("네")])
    fx = {"plugin_runner": plugin_runner, "session_memory": session_memory, "tool_registry": tool_registry,
          "skill_registry": skill_registry, "repo": jsonl_repo}
    await jsonl_repo.create(session_id="approval-rule")

    await _session(provider, permissive_pipeline, fx).prompt("안녕")

    assert "[도구 승인]" not in (provider.calls[-1].system_prompt or "")
