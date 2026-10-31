"""policy: 전부 허용 정책과 역할 기반 정책이 요청한 도구를 허용하거나 거부하는지 검증한다."""

import pytest

from jarvis.core.policy.pipeline import ANY_GRANT, AuthContext, PolicyDenied
from jarvis.core.policy.policy import AllowAllPolicy, RoleBasedPolicy

ROLES = {
    "admin": {"tools": ["*"], "skills": ["*"]},
    "user": {"tools": ["read_file", "search"], "skills": ["*"]},
}


@pytest.mark.parametrize(("tools", "allowed"), [(["bash", "search"], frozenset({"bash", "search"})), ([], ANY_GRANT)])
async def test_allow_all_grants_requested_tools_or_everything(tools, allowed):
    result = await AllowAllPolicy().check(AuthContext(user_id="u1", roles=frozenset({"user"})), tools)

    assert result.allowed_tools == allowed


@pytest.mark.parametrize(
    ("role", "tools", "granted"),
    [("admin", ["bash", "read_file"], "*"), ("user", ["read_file"], "read_file")],
)
async def test_role_based_grants_tools_of_the_role(role, tools, granted):
    result = await RoleBasedPolicy(ROLES).check(AuthContext(user_id="u1", roles=frozenset({role})), tools)

    assert granted in result.allowed_tools


@pytest.mark.parametrize(
    ("role", "tools", "match"),
    [("user", ["bash"], "not permitted"), ("guest", [], "no permissions")],
)
async def test_role_based_denies_tool_outside_role_or_unknown_role(role, tools, match):
    with pytest.raises(PolicyDenied, match=match):
        await RoleBasedPolicy(ROLES).check(AuthContext(user_id="u1", roles=frozenset({role})), tools)
