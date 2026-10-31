"""Web HUD 접근 키: Bearer 헤더 파싱과 키 → 사용자 조회."""

import pytest

from jarvis.ui.web.web_auth import auth_enabled, bearer_token, lookup_api_user
from jarvis.jarvis_config import ApiUser, JarvisSettings


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Bearer abc", "abc"),
        ("bearer  abc ", "abc"),
        ("BEARER abc", "abc"),
        ("Basic abc", None),
        ("Bearer", None),
        ("Bearer ", None),
        ("", None),
        (None, None),
    ],
)
def test_bearer_token(header, expected):
    assert bearer_token(header) == expected


def _settings(keys: dict[str, ApiUser]) -> JarvisSettings:
    settings = JarvisSettings()
    settings.security.api_keys = keys
    return settings


def test_auth_disabled_without_keys():
    assert auth_enabled(_settings({})) is False


def test_lookup_finds_user_by_key_and_rejects_others():
    alice = ApiUser(name="alice", roles=["admin"])
    settings = _settings({"k1": alice})
    assert auth_enabled(settings) is True
    assert lookup_api_user(settings, "k1") is alice
    assert lookup_api_user(settings, "wrong") is None
    assert lookup_api_user(settings, "") is None
    assert lookup_api_user(settings, None) is None
