from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable  # noqa: UP035

# ── 파이프라인 데이터 타입 (불변) ─────────────────────────────────────────────

@dataclass(frozen=True)
class ValidatedInput:
    raw: str
    sanitized: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    roles: frozenset[str]
    token: str | None = None
    is_anonymous: bool = False


@dataclass(frozen=True)
class PolicyResult:
    allowed_tools: frozenset[str]
    allowed_skills: frozenset[str]
    rate_limit: int | None = None
    reason: str = ""


@dataclass(frozen=True)
class ApprovalResult:
    approved: bool
    requires_human_review: bool = False
    blocked_reason: str | None = None


# ── 예외 ──────────────────────────────────────────────────────────────────────

class ValidationError(Exception):
    pass


class AuthError(Exception):
    pass


class PolicyDenied(Exception):
    pass


class SandboxBlocked(Exception):
    def __init__(self, reason: str, command: str) -> None:
        super().__init__(reason)
        self.command = command
        self.reason = reason


# ── 각 단계 Protocol ──────────────────────────────────────────────────────────

@runtime_checkable
class InputValidatorProtocol(Protocol):
    async def validate(self, raw_input: str) -> ValidatedInput: ...


@runtime_checkable
class AuthenticatorProtocol(Protocol):
    async def authenticate(self, validated: ValidatedInput, credentials: dict) -> AuthContext: ...


@runtime_checkable
class PolicyEngineProtocol(Protocol):
    async def check(self, auth_ctx: AuthContext, requested_tools: list[str]) -> PolicyResult: ...


@runtime_checkable
class SandboxProtocol(Protocol):
    async def approve(self, policy_result: PolicyResult, command: str) -> ApprovalResult: ...
    async def request_approval(self, command: str, reason: str, always_pattern: str = "") -> bool | str: ...
    def is_approval_required(self, tool_name: str) -> bool: ...
    async def authorize(self, tool_name: str, params: dict[str, Any]) -> bool: ...


# ── SecurityPipeline 오케스트레이터 ──────────────────────────────────────────

class SecurityPipeline:
    """
    4단계 보안 파이프라인 — agent loop 실행 전 강제 통과.
    순서 변경 불가, 구현체만 교체 가능.
    """

    def __init__(
        self,
        validator: InputValidatorProtocol,
        authenticator: AuthenticatorProtocol,
        policy: PolicyEngineProtocol,
        sandbox: SandboxProtocol,
    ) -> None:
        self._validator = validator
        self._authenticator = authenticator
        self._policy = policy
        self._sandbox = sandbox

    async def run(
        self,
        raw_input: str,
        credentials: dict,
        requested_tools: list[str] | None = None,
    ) -> tuple[ValidatedInput, AuthContext, PolicyResult]:
        validated = await self._validator.validate(raw_input)
        auth_ctx = await self._authenticator.authenticate(validated, credentials)
        policy_result = await self._policy.check(auth_ctx, requested_tools or [])
        return validated, auth_ctx, policy_result

    async def approve_tool_execution(
        self,
        policy_result: PolicyResult,
        command: str,
    ) -> ApprovalResult:
        return await self._sandbox.approve(policy_result, command)

    @property
    def sandbox(self) -> SandboxProtocol:
        return self._sandbox
