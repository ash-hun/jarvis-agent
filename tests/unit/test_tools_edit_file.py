"""tools 의 edit_file 내장 도구: 한 곳 또는 전부 바꾸고, 못 찾거나 모호하거나 파일이 없으면 오류인지 검증한다."""

import pytest

from jarvis.core.tools.builtin.edit_file import EditFileTool


@pytest.mark.parametrize(
    ("before", "params", "after"),
    [
        ("def foo():\n    pass\n", {"old_string": "pass", "new_string": "return 42"}, "def foo():\n    return 42\n"),
        ("x = 1\nx = 1\n", {"old_string": "x = 1", "new_string": "y = 2", "replace_all": True}, "y = 2\ny = 2\n"),
    ],
)
async def test_edit_file_replaces_text(tmp_path, before, params, after):
    f = tmp_path / "code.py"
    f.write_text(before)

    result = await EditFileTool().execute("c1", {"path": str(f), **params})

    assert result.is_error is False
    assert f.read_text() == after


@pytest.mark.parametrize(
    ("content", "old", "text"),
    [
        ("def foo(): pass\n", "MISSING", "not found"),
        ("x = 1\nx = 1\n", "x = 1", "replace_all"),
        (None, "x", "not found"),
    ],
)
async def test_edit_file_refuses_missing_ambiguous_or_absent(tmp_path, content, old, text):
    f = tmp_path / "code.py"
    if content is not None:
        f.write_text(content)

    result = await EditFileTool().execute("c1", {"path": str(f), "old_string": old, "new_string": "y"})

    assert result.is_error is True
    assert text in result.content[0].text
    if content is not None:
        assert f.read_text() == content
