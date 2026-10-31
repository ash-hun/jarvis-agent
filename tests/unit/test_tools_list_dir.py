"""tools 의 list_dir 내장 도구: 항목 나열, 숨김 파일 기본 제외와 all, 파일이나 없는 경로는 오류인지 검증한다."""

import pytest

from jarvis.core.tools.builtin.list_dir import ListDirTool


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "README.md").write_text("# Title\n")
    (tmp_path / ".hidden").write_text("secret\n")
    return tmp_path


@pytest.mark.parametrize(("show_all", "hidden_shown"), [(False, False), (True, True)])
async def test_list_dir_lists_entries_and_hidden_only_with_all(tree, show_all, hidden_shown):
    result = await ListDirTool().execute("c1", {"path": str(tree), "all": show_all})

    text = result.content[0].text
    assert "src/" in text and "README.md" in text
    assert (".hidden" in text) is hidden_shown


@pytest.mark.parametrize("relpath", ["README.md", "no/such/dir"])
async def test_list_dir_refuses_file_or_missing_path(tree, relpath):
    result = await ListDirTool().execute("c1", {"path": str(tree / relpath)})

    assert result.is_error is True
