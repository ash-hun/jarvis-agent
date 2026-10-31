"""policy: SecurityPipeline 이 검증, 인증, 정책을 차례로 통과시키고 단계별 실패와 위험 명령을 막는지 검증한다."""

import pytest

from jarvis.core.policy.pipeline import (
    AuthError,
    PolicyResult,
    SandboxBlocked,
    SecurityPipeline,
    ValidationError,
)
from jarvis.core.policy.authenticator import ApiKeyAuthenticator, NoAuthAuthenticator
from jarvis.core.policy.sandbox import DefaultSandbox, PermissiveSandbox
from jarvis.core.policy.validator import DefaultInputValidator
from jarvis.core.policy.policy import AllowAllPolicy


def _pipeline(authenticator=None, sandbox=None) -> SecurityPipeline:
    return SecurityPipeline(
        validator=DefaultInputValidator(),
        authenticator=authenticator or NoAuthAuthenticator(),
        policy=AllowAllPolicy(),
        sandbox=sandbox or PermissiveSandbox(),
    )


async def test_run_passes_all_steps(permissive_pipeline):
    validated, auth, policy = await permissive_pipeline.run(
        raw_input="Hello Jarvis", credentials={}, requested_tools=["bash"]
    )

    assert validated.sanitized == "Hello Jarvis"
    assert auth.user_id == "local"
    assert policy.allowed_tools


@pytest.mark.parametrize(
    ("authenticator", "raw", "credentials", "error"),
    [
        (None, "", {}, ValidationError),
        (None, "<script>alert(1)</script>", {}, ValidationError),
        (ApiKeyAuthenticator({"valid-key": frozenset({"user"})}), "Hello", {"api_key": "wrong"}, AuthError),
    ],
    ids=["empty_at_step1", "xss_at_step1", "invalid_key_at_step2"],
)
async def test_run_fails_at_the_failing_step(authenticator, raw, credentials, error):
    with pytest.raises(error):
        await _pipeline(authenticator).run(raw, credentials=credentials)


async def test_approve_tool_execution_blocks_dangerous_command():
    policy = PolicyResult(allowed_tools=frozenset({"*"}), allowed_skills=frozenset({"*"}))

    with pytest.raises(SandboxBlocked):
        await _pipeline(sandbox=DefaultSandbox()).approve_tool_execution(policy_result=policy, command="rm -rf /")
