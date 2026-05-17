from __future__ import annotations

import re
from typing import Awaitable, Callable

from jarvis.core.policy.pipeline import ApprovalResult, PolicyResult, SandboxBlocked


class DefaultSandbox:
    """
    Step 4: 실행 샌드박스.
    - 위험 명령어 패턴 차단
    - require_approval 툴 목록에 대해 Human-in-the-loop 승인 플로우
    """

    def __init__(
        self,
        dangerous_patterns: list[str] | None = None,
        require_approval_for: list[str] | None = None,
        approval_callback: Callable[[str, str], Awaitable[bool]] | None = None,
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

    async def request_approval(self, command: str, reason: str) -> bool:
        """Human-in-the-loop 승인 요청. approval_callback이 없으면 자동 거부."""
        if self._approval_callback:
            return await self._approval_callback(command, reason)
        return False

    def is_approval_required(self, tool_name: str) -> bool:
        return tool_name in self._require_approval


class PermissiveSandbox:
    """모든 명령 허용. 개발/테스트 전용."""

    async def approve(self, policy_result: PolicyResult, command: str) -> ApprovalResult:
        return ApprovalResult(approved=True)

    async def request_approval(self, command: str, reason: str) -> bool:
        return True
