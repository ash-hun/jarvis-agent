from __future__ import annotations

from jarvis.core.policy.pipeline import AuthContext, AuthError, ValidatedInput
from jarvis.memory.scope import LOCAL_USER


class NoAuthAuthenticator:
    """인증 없이 anonymous 사용자로 통과. 개인 비서 단독 사용 시."""

    def __init__(self, default_roles: frozenset[str] | None = None) -> None:
        self._roles = default_roles or frozenset({"user"})

    async def authenticate(
        self,
        validated: ValidatedInput,
        credentials: dict,
    ) -> AuthContext:
        return AuthContext(
            user_id=LOCAL_USER,
            roles=self._roles,
            is_anonymous=True,
        )


class ApiKeyAuthenticator:
    """
    API key 기반 인증. credentials["api_key"]와 미리 설정된 키를 비교.
    """

    def __init__(
        self,
        valid_keys: dict[str, frozenset[str]],
        user_names: dict[str, str] | None = None,
    ) -> None:
        self._keys = valid_keys
        self._names = user_names or {}

    async def authenticate(
        self,
        validated: ValidatedInput,
        credentials: dict,
    ) -> AuthContext:
        api_key = credentials.get("api_key", "")
        if not api_key:
            raise AuthError("API key is required")
        if api_key not in self._keys:
            raise AuthError("Invalid API key")
        return AuthContext(
            user_id=self._names.get(api_key, api_key[:8] + "..."),
            roles=self._keys[api_key],
            token=api_key,
        )
