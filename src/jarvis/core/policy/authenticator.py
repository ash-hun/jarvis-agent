"""[core] 보안 파이프라인 Step 2 의 인증기 구현체(익명 통과, API key)를 제공한다."""

from __future__ import annotations

from typing import Any

from jarvis.core.policy.pipeline import (
    ANONYMOUS_ROLES,
    AuthContext,
    AuthenticatorProtocol,
    AuthError,
    ValidatedInput,
)


class NoAuthAuthenticator(AuthenticatorProtocol):
    """인증 없이 anonymous 사용자로 통과. 개인 비서 단독 사용 시. authenticate 는 기반의 NoAuth 동작을 쓴다."""

    def __init__(self, default_roles: frozenset[str] | None = None) -> None:
        self._roles = default_roles or ANONYMOUS_ROLES


class ApiKeyAuthenticator(AuthenticatorProtocol):
    """API key 기반 인증. credentials["api_key"]와 미리 설정된 키를 비교."""

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
        credentials: dict[str, Any],
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
