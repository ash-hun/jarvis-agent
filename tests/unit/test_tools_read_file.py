"""tools 의 read_file 내장 도구: 파일 내용을 limit 만큼 읽고 없는 파일은 오류로 알리는지 검증한다."""

from jarvis.core.tools.builtin.read_file import ReadFileTool


async def test_read_file_returns_content(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("line1\nline2\nline3\n")

    result = await ReadFileTool().execute("c1", {"path": str(f)})

    assert result.is_error is False
    assert "line1" in result.content[0].text


async def test_read_file_limit_caps_lines(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("\n".join(f"line {i}" for i in range(100)))

    result = await ReadFileTool().execute("c1", {"path": str(f), "limit": 5})

    assert result.is_error is False
    assert len(result.content[0].text.strip().split("\n")) == 5


async def test_read_file_missing_is_error():
    result = await ReadFileTool().execute("c1", {"path": "/nonexistent/path.txt"})

    assert result.is_error is True
    assert "not found" in result.content[0].text
