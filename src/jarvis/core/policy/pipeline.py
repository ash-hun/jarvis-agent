"""[core] 4단계 보안 파이프라인(검증, 인증, 정책, 샌드박스)의 데이터 타입, 예외, 단계 기반 클래스를 정한다."""

from typing import Any, Literal
from dataclasses import dataclass, field

from jarvis.memory.scope import LOCAL_USER

# 단계 기반 클래스의 기본 동작은 개인 비서 단독 사용(검증 없음, 익명 사용자, 전부 허용)이다
ANONYMOUS_ROLES: frozenset[str] = frozenset({"user"})
ANY_GRANT: frozenset[str] = frozenset({"*"})
# 도구 실행 결정. timeout 은 승인 요청에 사용자가 시간 안에 답하지 않은 거부다
Decision = Literal["allow", "deny", "timeout"]

# ── 파이프라인 데이터 타입 (불변) ─────────────────────────────────────────────

@dataclass(frozen=True)
class ValidatedInput:
    raw: str
    sanitized: str
    metadata: dict[str, Any] = field(default_factory=dict)


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


# ── 각 단계 기반 클래스 ────────────────────────────────────────────────────────

class InputValidatorProtocol:
    """Step 1 기반. 기본은 검증 없이 원문을 그대로 통과시킨다. DefaultInputValidator 가 실제 검증을 한다."""

    async def validate(self, raw_input: str) -> ValidatedInput:
        return ValidatedInput(raw=raw_input, sanitized=raw_input)


class AuthenticatorProtocol:
    """Step 2 기반. 기본은 인증 없이 _roles 를 가진 익명 로컬 사용자로 통과(NoAuth)."""

    _roles: frozenset[str] = ANONYMOUS_ROLES

    async def authenticate(self, validated: ValidatedInput, credentials: dict[str, Any]) -> AuthContext:
        return AuthContext(
            user_id=LOCAL_USER,
            roles=self._roles,
            is_anonymous=True,
        )


class PolicyEngineProtocol:
    """Step 3 기반. 기본은 요청한 툴(없으면 전부)과 모든 스킬을 허용(AllowAll)."""

    async def check(self, auth_ctx: AuthContext, requested_tools: list[str]) -> PolicyResult:
        return PolicyResult(
            allowed_tools=frozenset(requested_tools) if requested_tools else ANY_GRANT,
            allowed_skills=ANY_GRANT,
        )


class SandboxProtocol:
    """Step 4 기반. 기본은 모든 명령 허용, 승인 불필요(Permissive)."""

    async def approve(self, policy_result: PolicyResult, command: str) -> ApprovalResult:
        return ApprovalResult(approved=True)

    async def request_approval(self, command: str, reason: str, always_pattern: str = "") -> bool | str:
        return True

    def is_approval_required(self, tool_name: str) -> bool:
        return False

    def approval_tools(self) -> list[str]:
        return []

    async def authorize(self, tool_name: str, params: dict[str, Any]) -> bool:
        return True

    async def decide(self, tool_name: str, params: dict[str, Any]) -> Decision:
        """authorize 와 같되 거부 이유(사용자 거부, 시간 초과)까지 돌려준다. 기본은 authorize 를 따른다."""
        return "allow" if await self.authorize(tool_name, params) else "deny"


# ── SecurityPipeline 오케스트레이터 ──────────────────────────────────────────

class SecurityPipeline:
    """4단계 보안 파이프라인. agent loop 실행 전 강제 통과. 순서 변경 불가, 구현체만 교체 가능."""

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
        credentials: dict[str, Any],
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
