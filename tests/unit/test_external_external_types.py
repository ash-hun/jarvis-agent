"""external 기능의 이벤트 모델: 한 줄 표현에서 본문을 넣고 빼는 규칙을 검증한다."""

import pytest

from tests.fixtures.external_helpers import event


@pytest.mark.parametrize(
    ("title", "include_detail", "present", "absent"),
    [
        ("제목", True, ["본문 비밀"], []),
        ("제목", False, ["제목"], ["본문 비밀"]),
        ("", False, ["본문 비밀"], []),
    ],
    ids=["detail_included", "detail_hidden", "falls_back_to_detail_without_title"],
)
def test_as_line_includes_detail_only_when_requested_or_untitled(
    title: str, include_detail: bool, present: list[str], absent: list[str]
) -> None:
    item = event("mail", "mail:1", title=title, detail="본문 비밀", occurred_at="10:00")

    line = item.as_line(include_detail=include_detail)

    assert all(text in line for text in present)
    assert not any(text in line for text in absent)
