"""tools 의 write_file 내장 도구: 새 파일, 덮어쓰기, 상위 디렉터리 생성, 쓴 바이트 수 보고를 검증한다."""

import pytest

from jarvis.core.tools.builtin.write_file import WriteFileTool


@pytest.mark.parametrize(("relpath", "existing"), [("out.txt", None), ("out.txt", "old content"), ("a/b/c.txt", None)])
async def test_write_file_writes_content(tmp_path, relpath, existing):
    f = tmp_path / relpath
    if existing is not None:
        f.write_text(existing)

    result = await WriteFileTool().execute("c1", {"path": str(f), "content": "abc"})

    assert result.is_error is False
    assert f.read_text() == "abc"
    assert "3" in result.content[0].text
