"""tools 의 glob 내장 도구: 재귀 패턴, 일치 없음, limit, 없는 디렉터리를 검증한다."""

import pytest

from jarvis.core.tools.builtin.glob import GlobTool


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x\n")
    (tmp_path / "src" / "util.py").write_text("y\n")
    return tmp_path


async def test_glob_matches_recursively(tree):
    result = await GlobTool().execute("c1", {"pattern": "**/*.py", "path": str(tree)})

    assert result.is_error is False
    assert "main.py" in result.content[0].text and "util.py" in result.content[0].text


async def test_glob_limit_caps_results(tree):
    result = await GlobTool().execute("c1", {"pattern": "**/*.py", "path": str(tree), "limit": 1})

    body = result.content[0].text.split("\n", 1)[1]
    assert len(body.strip().splitlines()) == 1


async def test_glob_no_match_is_not_an_error(tree):
    result = await GlobTool().execute("c1", {"pattern": "**/*.rs", "path": str(tree)})

    assert result.is_error is False
    assert "No files matching" in result.content[0].text


async def test_glob_missing_dir_is_error():
    result = await GlobTool().execute("c1", {"pattern": "*", "path": "/no/such/dir"})

    assert result.is_error is True
