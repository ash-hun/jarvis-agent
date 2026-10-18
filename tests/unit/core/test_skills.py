"""core/skills/ — SkillRegistry + /command 확장 테스트."""
import pytest

from jarvis.core.skills.registry import Skill, SkillRegistry


@pytest.fixture
def registry():
    return SkillRegistry()


@pytest.fixture
def hello_skill():
    return Skill(
        name="hello",
        description="Say hello",
        aliases=["hi", "greet"],
        content="Say hello to {{args}}",
        metadata={},
    )


class TestSkillRegistry:
    def test_register_and_get_by_name(self, registry, hello_skill):
        registry.register(hello_skill)
        skill = registry.get("hello")
        assert skill is not None
        assert skill.name == "hello"

    def test_get_by_alias(self, registry, hello_skill):
        registry.register(hello_skill)
        skill = registry.get("hi")
        assert skill is not None
        assert skill.name == "hello"

    def test_get_nonexistent_returns_none(self, registry):
        assert registry.get("nonexistent") is None

    def test_unregister(self, registry, hello_skill):
        registry.register(hello_skill)
        registry.unregister("hello")
        assert registry.get("hello") is None
        assert registry.get("hi") is None

    def test_list_all(self, registry, hello_skill):
        registry.register(hello_skill)
        skills = registry.list_all()
        assert len(skills) == 1

    def test_expand_slash_command(self, registry, hello_skill):
        registry.register(hello_skill)
        result = registry.expand("/hello World")
        assert "World" in result

    def test_expand_alias(self, registry, hello_skill):
        registry.register(hello_skill)
        result = registry.expand("/hi Jarvis")
        assert "Jarvis" in result

    def test_expand_unknown_command_passthrough(self, registry):
        result = registry.expand("/unknown command")
        assert result == "/unknown command"

    def test_no_slash_passthrough(self, registry, hello_skill):
        registry.register(hello_skill)
        result = registry.expand("plain text")
        assert result == "plain text"


class TestSkillFileLoading:
    async def test_load_markdown_skill(self, registry, tmp_path):
        md_file = tmp_path / "summary.md"
        md_file.write_text(
            "---\n"
            "name: summary\n"
            "description: Summarize text\n"
            "aliases: [sum]\n"
            "---\n"
            "Please summarize: {{args}}"
        )
        loaded = await registry.load_directory(str(tmp_path))
        assert "summary" in loaded
        skill = registry.get("summary")
        assert skill is not None
        assert registry.get("sum") is not None

    async def test_load_yaml_skill(self, registry, tmp_path):
        yaml_file = tmp_path / "translate.yaml"
        yaml_file.write_text(
            "name: translate\n"
            "description: Translate text\n"
            "aliases: [tr]\n"
            "content: 'Translate to Korean: {{args}}'\n"
        )
        loaded = await registry.load_directory(str(tmp_path))
        assert "translate" in loaded

    async def test_load_empty_directory(self, registry, tmp_path):
        loaded = await registry.load_directory(str(tmp_path))
        assert loaded == []

    async def test_load_nonexistent_directory(self, registry):
        loaded = await registry.load_directory("/nonexistent/path")
        assert loaded == []
