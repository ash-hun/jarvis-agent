"""[core] 보안 파이프라인 Step 1 의 기본 입력 검증기(길이, 금지 패턴, 정규화, 이스케이프)를 제공한다."""

import re
import html
import unicodedata

from jarvis.core.policy.pipeline import InputValidatorProtocol, ValidatedInput, ValidationError


class DefaultInputValidator(InputValidatorProtocol):
    """Step 1: 입력 검증. 길이/패턴/인코딩 정규화, XSS 방어."""

    def __init__(
        self,
        max_length: int = 10_000,
        disallow_patterns: list[str] | None = None,
    ) -> None:
        self._max_length = max_length
        self._disallow_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in (disallow_patterns or [
                r"<script[^>]*>",
                r"javascript\s*:",
                r"on\w+\s*=",
            ])
        ]

    async def validate(self, raw_input: str) -> ValidatedInput:
        if not raw_input or not raw_input.strip():
            raise ValidationError("Input must not be empty")

        if len(raw_input) > self._max_length:
            raise ValidationError(
                f"Input exceeds maximum length of {self._max_length} characters"
            )

        normalized = unicodedata.normalize("NFC", raw_input)

        for pattern in self._disallow_patterns:
            if pattern.search(normalized):
                raise ValidationError(f"Input contains disallowed pattern: {pattern.pattern}")

        sanitized = html.escape(normalized, quote=False)
        return ValidatedInput(
            raw=raw_input,
            sanitized=sanitized.strip(),
            metadata={"length": len(raw_input)},
        )
