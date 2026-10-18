"""[core] 보안 파이프라인 Step 3 의 정책 엔진 구현체(전부 허용, 역할 기반)를 제공한다."""

from jarvis.core.policy.pipeline import AuthContext, PolicyDenied, PolicyEngineProtocol, PolicyResult


class AllowAllPolicy(PolicyEngineProtocol):
    """모든 툴/스킬 허용. 개인 단독 사용 시. check 는 기반의 AllowAll 동작을 쓴다."""


class RoleBasedPolicy(PolicyEngineProtocol):
    """역할(role) 기반 접근 통제. role_permissions: {"admin": {"tools": ["*"], "skills": ["*"]}, "user": {...}}"""

    def __init__(self, role_permissions: dict[str, dict[str, list[str]]]) -> None:
        self._permissions = role_permissions

    async def check(
        self,
        auth_ctx: AuthContext,
        requested_tools: list[str],
    ) -> PolicyResult:
        allowed_tools: set[str] = set()
        allowed_skills: set[str] = set()

        for role in auth_ctx.roles:
            perms = self._permissions.get(role, {})
            tools = perms.get("tools", [])
            skills = perms.get("skills", [])
            if "*" in tools:
                allowed_tools.add("*")
            else:
                allowed_tools.update(tools)
            if "*" in skills:
                allowed_skills.add("*")
            else:
                allowed_skills.update(skills)

        if not allowed_tools and not allowed_skills:
            raise PolicyDenied(
                f"User '{auth_ctx.user_id}' with roles {set(auth_ctx.roles)} has no permissions"
            )

        if "*" not in allowed_tools and requested_tools:
            denied = [t for t in requested_tools if t not in allowed_tools]
            if denied:
                raise PolicyDenied(f"Tools not permitted: {denied}")

        return PolicyResult(
            allowed_tools=frozenset(allowed_tools),
            allowed_skills=frozenset(allowed_skills),
            reason=f"Granted for roles: {set(auth_ctx.roles)}",
        )
