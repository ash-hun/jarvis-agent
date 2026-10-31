"""policy: 익명 인증기는 기본 또는 지정 역할로 통과시키고 API key 인증기는 키로 역할과 이름을 찾는지 검증한다."""

import pytest

from jarvis.core.policy.authenticator import ApiKeyAuthenticator, NoAuthAuthenticator
from jarvis.core.policy.pipeline import AuthError, ValidatedInput

VALIDATED = ValidatedInput(raw="hi", sanitized="hi")
KEYS = {"valid-key-001": frozenset({"user"}), "admin-key-002": frozenset({"admin", "user"})}


@pytest.mark.parametrize(("roles", "expected_role"), [(None, "user"), (frozenset({"admin"}), "admin")])
async def test_no_auth_passes_as_local_with_roles(roles, expected_role):
    ctx = await NoAuthAuthenticator(default_roles=roles).authenticate(VALIDATED, {})

    assert ctx.user_id == "local"
    assert ctx.is_anonymous is True
    assert expected_role in ctx.roles


@pytest.mark.parametrize("key", ["valid-key-001", "admin-key-002"])
async def test_api_key_grants_roles_of_the_key(key):
    ctx = await ApiKeyAuthenticator(KEYS).authenticate(VALIDATED, {"api_key": key})

    assert ctx.roles == KEYS[key]


@pytest.mark.parametrize(("credentials", "match"), [({}, "required"), ({"api_key": "wrong-key"}, "Invalid")])
async def test_api_key_rejects_missing_or_unknown_key(credentials, match):
    with pytest.raises(AuthError, match=match):
        await ApiKeyAuthenticator(KEYS).authenticate(VALIDATED, credentials)


async def test_api_key_maps_key_to_user_name():
    auth = ApiKeyAuthenticator(valid_keys={"k-123": frozenset({"admin"})}, user_names={"k-123": "jh"})

    ctx = await auth.authenticate(VALIDATED, {"api_key": "k-123"})

    assert ctx.user_id == "jh" and ctx.roles == frozenset({"admin"})
