"""[core] 보안 파이프라인 Step 4 의 샌드박스 구현체(위험 명령 차단과 승인 흐름, 전부 허용)를 제공한다."""

import re
from typing import Any
from collections.abc import Awaitable, Callable

from jarvis.core.policy.pipeline import ApprovalResult, Decision, PolicyResult, SandboxBlocked, SandboxProtocol
from jarvis.core.policy.approval_rules import ApprovalRule, ApprovalRules, describe, suggest_pattern

# 승인 콜백의 답. True/False 는 이번 한 번, "always" 는 제안된 패턴을 규칙으로 남긴다.
ApprovalChoice = bool | str
ApprovalCallback = Callable[[str, str, str], Awaitable[ApprovalChoice]]
ALWAYS = "always"
# 승인 창이 시간 안에 답을 받지 못했다. 거부와 같지만 사용자에게 다르게 알린다
TIMEOUT = "timeout"


class DefaultSandbox(SandboxProtocol):
    """Step 4: 실행 샌드박스.

    - 위험 명령어 패턴 차단
    - require_approval 툴 목록에 대해 Human-in-the-loop 승인 플로우
    - 승인 기억(approval_rules): 사용자가 "항상 허용"한 패턴은 다시 묻지 않는다
    """

    def __init__(
        self,
        dangerous_patterns: list[str] | None = None,
        require_approval_for: list[str] | None = None,
        approval_callback: ApprovalCallback | None = None,
        approval_rules: ApprovalRules | None = None,
    ) -> None:
        self._patterns = [
            re.compile(p, re.IGNORECASE)
            for p in (dangerous_patterns or [
                r"rm\s+-rf\s+/",
                r"sudo\s+",
                r"curl\s+.*\|\s*(ba)?sh",
                r"wget\s+.*\|\s*(ba)?sh",
                r">\s*/dev/(sda|hda|nvme)",
                r"mkfs\.",
                r"dd\s+if=.*of=/dev/",
                r":(){ :|:& };:",  # fork bomb
            ])
        ]
        self._require_approval = set(require_approval_for or ["bash", "write_file"])
        self._approval_callback = approval_callback
        self._rules = approval_rules

    async def approve(
        self,
        policy_result: PolicyResult,
        command: str,
    ) -> ApprovalResult:
        for pattern in self._patterns:
            if pattern.search(command):
                raise SandboxBlocked(
                    reason=f"Blocked by sandbox: dangerous pattern '{pattern.pattern}'",
                    command=command,
                )

        return ApprovalResult(approved=True)

    async def request_approval(self, command: str, reason: str, always_pattern: str = "") -> ApprovalChoice:
        """Human-in-the-loop 승인 요청. approval_callback이 없으면 자동 거부."""
        if self._approval_callback:
            return await self._approval_callback(command, reason, always_pattern)
        return False

    async def authorize(self, tool_name: str, params: dict[str, Any]) -> bool:
        return await self.decide(tool_name, params) == "allow"

    async def decide(self, tool_name: str, params: dict[str, Any]) -> Decision:
        """이 호출을 실행해도 되는가. 승인 불필요 → 기억된 규칙 → 사용자에게 질문 순으로 결정한다.

        규칙은 사용자가 승인 화면에서 "항상 허용"을 골랐을 때만 생긴다. 코드가 먼저 넓히지 않는다.
        """
        if not self.is_approval_required(tool_name):
            return "allow"
        if self._rules is not None and self._rules.allows(tool_name, params):
            return "allow"
        pattern = suggest_pattern(tool_name, params) if self._rules is not None else ""
        choice = await self.request_approval(
            command=describe(tool_name, params),
            reason=f"Tool '{tool_name}' requires approval",
            always_pattern=pattern,
        )
        if choice == ALWAYS:
            if self._rules is not None and pattern:
                self._rules.add(ApprovalRule(tool=tool_name, pattern=pattern))
            return "allow"
        if choice == TIMEOUT:
            return "timeout"
        return "allow" if choice is True else "deny"

    def set_approval_callback(self, callback: ApprovalCallback) -> None:
        self._approval_callback = callback

    def set_approval_rules(self, rules: ApprovalRules | None) -> None:
        """세션의 에이전트가 정해진 뒤 그 에이전트의 승인 규칙으로 바꾼다(TUI 가 기동 때 부른다)."""
        self._rules = rules

    def is_approval_required(self, tool_name: str) -> bool:
        return tool_name in self._require_approval

    def approval_tools(self) -> list[str]:
        return sorted(self._require_approval)


class PermissiveSandbox(SandboxProtocol):
    """모든 명령 허용. 개발/테스트 전용. 네 메서드 모두 기반의 Permissive 동작을 쓴다."""
