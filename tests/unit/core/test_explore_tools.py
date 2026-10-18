"""탐색 계열 내장 툴 테스트 — glob, grep, list_dir, web_fetch."""
import pytest


@pytest.fixture
def sample_tree(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("import os\n\ndef run():\n    return 42\n")
    (tmp_path / "src" / "util.py").write_text("def helper():\n    pass\n")
    (tmp_path / "README.md").write_text("# Title\nsome TODO here\n")
    (tmp_path / ".hidden").write_text("secret\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.py").write_text("TODO cached\n")
    return tmp_path


# ── GlobTool ──────────────────────────────────────────────────────────────────

class TestGlobTool:
    @pytest.fixture
    def tool(self):
        from jarvis.core.tools.builtin.glob import GlobTool
        return GlobTool()

    async def test_recursive_match(self, tool, sample_tree):
        result = await tool.execute("c1", {"pattern": "**/*.py", "path": str(sample_tree)})
        assert result.is_error is False
        text = result.content[0].text
        assert "main.py" in text
        assert "util.py" in text

    async def test_no_match(self, tool, sample_tree):
        result = await tool.execute("c1", {"pattern": "**/*.rs", "path": str(sample_tree)})
        assert result.is_error is False
        assert "No files matching" in result.content[0].text

    async def test_limit(self, tool, sample_tree):
        result = await tool.execute(
            "c1", {"pattern": "**/*.py", "path": str(sample_tree), "limit": 1}
        )
        body = result.content[0].text.split("\n", 1)[1]
        assert len(body.strip().splitlines()) == 1

    async def test_missing_dir(self, tool):
        result = await tool.execute("c1", {"pattern": "*", "path": "/no/such/dir"})
        assert result.is_error is True


# ── GrepTool ──────────────────────────────────────────────────────────────────

class TestGrepTool:
    @pytest.fixture
    def tool(self):
        from jarvis.core.tools.builtin.grep import GrepTool
        return GrepTool()

    async def test_finds_match_with_location(self, tool, sample_tree):
        result = await tool.execute("c1", {"pattern": "def run", "path": str(sample_tree)})
        assert result.is_error is False
        assert "main.py:3:" in result.content[0].text

    async def test_glob_filter(self, tool, sample_tree):
        result = await tool.execute(
            "c1", {"pattern": "TODO", "path": str(sample_tree), "glob": "*.md"}
        )
        assert "README.md" in result.content[0].text

    async def test_skips_pycache(self, tool, sample_tree):
        result = await tool.execute("c1", {"pattern": "TODO", "path": str(sample_tree)})
        assert "__pycache__" not in result.content[0].text

    async def test_case_insensitive(self, tool, sample_tree):
        result = await tool.execute(
            "c1", {"pattern": "todo", "path": str(sample_tree), "case_insensitive": True}
        )
        assert "README.md" in result.content[0].text

    async def test_no_match(self, tool, sample_tree):
        result = await tool.execute("c1", {"pattern": "zzz_no_match", "path": str(sample_tree)})
        assert "No matches" in result.content[0].text

    async def test_invalid_regex(self, tool, sample_tree):
        result = await tool.execute("c1", {"pattern": "[", "path": str(sample_tree)})
        assert result.is_error is True
        assert "Invalid regex" in result.content[0].text


# ── ListDirTool ───────────────────────────────────────────────────────────────

class TestListDirTool:
    @pytest.fixture
    def tool(self):
        from jarvis.core.tools.builtin.list_dir import ListDirTool
        return ListDirTool()

    async def test_lists_entries(self, tool, sample_tree):
        result = await tool.execute("c1", {"path": str(sample_tree)})
        text = result.content[0].text
        assert "src/" in text
        assert "README.md" in text

    async def test_hidden_excluded_by_default(self, tool, sample_tree):
        result = await tool.execute("c1", {"path": str(sample_tree)})
        assert ".hidden" not in result.content[0].text

    async def test_hidden_with_all(self, tool, sample_tree):
        result = await tool.execute("c1", {"path": str(sample_tree), "all": True})
        assert ".hidden" in result.content[0].text

    async def test_not_a_directory(self, tool, sample_tree):
        result = await tool.execute("c1", {"path": str(sample_tree / "README.md")})
        assert result.is_error is True

    async def test_missing(self, tool):
        result = await tool.execute("c1", {"path": "/no/such/dir"})
        assert result.is_error is True


# ── WebFetchTool ──────────────────────────────────────────────────────────────

class TestWebFetchTool:
    @pytest.fixture
    def tool(self):
        from jarvis.core.tools.builtin.web_fetch import WebFetchTool
        return WebFetchTool()

    async def test_rejects_non_http(self, tool):
        result = await tool.execute("c1", {"url": "ftp://example.com"})
        assert result.is_error is True
        assert "Invalid URL" in result.content[0].text

    def test_html_to_text_strips_tags(self):
        from jarvis.core.tools.builtin.web_fetch import _html_to_text

        html = "<html><head><style>x{}</style></head><body><h1>Hi</h1><p>World &amp; more</p></body></html>"
        text = _html_to_text(html)
        assert "Hi" in text
        assert "World & more" in text
        assert "<" not in text
        assert "x{}" not in text

    async def test_fetch_mocked(self, tool, monkeypatch):
        import httpx

        def handler(request):
            return httpx.Response(200, html="<html><body><p>Hello page</p></body></html>")

        transport = httpx.MockTransport(handler)
        orig_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            orig_init(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

        result = await tool.execute("c1", {"url": "https://example.com"})
        assert result.is_error is False
        assert "Hello page" in result.content[0].text
