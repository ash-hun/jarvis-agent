"""policy: 입력 검증기가 빈 입력, 너무 긴 입력, 금지 패턴을 막고 남은 입력을 정규화하고 이스케이프하는지 검증한다."""

import pytest

from jarvis.core.policy.validator import DefaultInputValidator
from jarvis.core.policy.pipeline import ValidationError


@pytest.mark.parametrize(
    ("raw", "sanitized"),
    [
        ("Hello, Jarvis!", "Hello, Jarvis!"),
        ("Hello <b>world</b>", "Hello &lt;b&gt;world&lt;/b&gt;"),
        ("café", "café"),
    ],
    ids=["plain", "html_escaped", "unicode_nfc"],
)
async def test_validate_keeps_raw_and_sanitizes(raw, sanitized):
    result = await DefaultInputValidator().validate(raw)

    assert result.raw == raw
    assert result.sanitized == sanitized


@pytest.mark.parametrize(
    ("max_length", "raw", "match"),
    [
        (10_000, "", "empty"),
        (10_000, "   ", "empty"),
        (10, "A" * 11, "maximum length"),
        (10_000, "<script>alert('xss')</script>", "disallowed pattern"),
    ],
    ids=["empty", "whitespace", "too_long", "xss"],
)
async def test_validate_rejects_bad_input(max_length, raw, match):
    with pytest.raises(ValidationError, match=match):
        await DefaultInputValidator(max_length=max_length).validate(raw)
