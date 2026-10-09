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


class JWTAuthenticator:
    """JWT 토큰 기반 인증. credentials["token"] 검증."""

    def __init__(self, secret: str, algorithm: str = "HS256") -> None:
        self._secret = secret
        self._algorithm = algorithm

    async def authenticate(
        self,
        validated: ValidatedInput,
        credentials: dict,
    ) -> AuthContext:
        try:
            from jose import jwt
        except ImportError as exc:
            raise ImportError("python-jose is required: pip install python-jose[cryptography]") from exc

        token = credentials.get("token", "")
        if not token:
            raise AuthError("JWT token is required")

        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except Exception as exc:
            raise AuthError(f"Invalid token: {exc}") from exc

        return AuthContext(
            user_id=payload.get("sub", "unknown"),
            roles=frozenset(payload.get("roles", ["user"])),
            token=token,
        )
