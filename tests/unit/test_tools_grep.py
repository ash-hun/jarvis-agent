"""tools 의 grep 내장 도구: 위치, glob 필터, 대소문자, __pycache__ 제외, 일치 없음, 잘못된 정규식을 검증한다."""

import pytest

from jarvis.core.tools.builtin.grep import GrepTool


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("import os\n\ndef run():\n    return 42\n")
    (tmp_path / "README.md").write_text("# Title\nsome TODO here\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.py").write_text("TODO cached\n")
    return tmp_path


@pytest.mark.parametrize(
    ("params", "present", "absent"),
    [
        ({"pattern": "def run"}, "main.py:3:", None),
        ({"pattern": "TODO", "glob": "*.md"}, "README.md", None),
        ({"pattern": "TODO"}, "README.md", "__pycache__"),
        ({"pattern": "todo", "case_insensitive": True}, "README.md", None),
        ({"pattern": "zzz_no_match"}, "No matches", None),
    ],
)
async def test_grep_finds_matches(tree, params, present, absent):
    result = await GrepTool().execute("c1", {**params, "path": str(tree)})

    assert result.is_error is False
    assert present in result.content[0].text
    if absent:
        assert absent not in result.content[0].text


async def test_grep_invalid_regex_is_error(tree):
    result = await GrepTool().execute("c1", {"pattern": "[", "path": str(tree)})

    assert result.is_error is True
    assert "Invalid regex" in result.content[0].text
