"""skills 의 SkillRegistry: md/yaml 로드, 이름과 별칭 조회, '/스킬 인자' 확장, 잘못된 파일 건너뛰기를 검증한다."""

import pytest

from jarvis.core.skills.skills_registry import Skill, SkillRegistry


@pytest.fixture
def registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(Skill(
        name="hello", description="Say hello", aliases=["hi", "greet"], content="Say hello to {{args}}", metadata={}
    ))
    return registry


@pytest.mark.parametrize("key", ["hello", "hi", "greet"])
def test_get_finds_skill_by_name_or_alias(registry, key):
    skill = registry.get(key)

    assert skill is not None and skill.name == "hello"


def test_get_unknown_returns_none(registry):
    assert registry.get("nonexistent") is None


def test_unregister_removes_name_and_aliases(registry):
    registry.unregister("hello")
    registry.unregister("hello")

    assert registry.get("hello") is None and registry.get("hi") is None
    assert registry.list_all() == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/hello World", "Say hello to World"),
        ("/hi Jarvis and friends", "Say hello to Jarvis and friends"),
        ("/hello", "Say hello to "),
    ],
)
def test_expand_substitutes_args_into_skill_content(registry, text, expected):
    assert registry.expand(text) == expected


def test_expand_substitutes_input_placeholder_too():
    registry = SkillRegistry()
    registry.register(Skill(name="echo", description="", aliases=[], content="[{{input}}|{{args}}]", metadata={}))

    assert registry.expand("/echo a b") == "[a b|a b]"


@pytest.mark.parametrize("text", ["/unknown command", "plain text", "say /hello later"])
def test_expand_passes_through_non_skill_input(registry, text):
    assert registry.expand(text) == text


async def test_load_directory_reads_markdown_and_yaml_skills(tmp_path):
    (tmp_path / "summary.md").write_text(
        "---\nname: summary\ndescription: Summarize text\naliases: [sum]\n---\nPlease summarize: {{args}}"
    )
    (tmp_path / "translate.yaml").write_text(
        "name: translate\ndescription: Translate text\naliases: [tr]\ncontent: 'Translate to Korean: {{args}}'\n"
    )
    (tmp_path / "notes.txt").write_text("not a skill")
    registry = SkillRegistry()

    loaded = await registry.load_directory(str(tmp_path))

    assert sorted(loaded) == ["summary", "translate"]
    assert registry.get("sum").description == "Summarize text"
    assert registry.expand("/sum 긴 글") == "Please summarize: 긴 글"
    assert registry.expand("/tr hello") == "Translate to Korean: hello"


async def test_load_directory_names_skill_after_file_when_name_missing(tmp_path):
    (tmp_path / "bare.md").write_text("본문 {{args}}")
    registry = SkillRegistry()

    assert await registry.load_directory(str(tmp_path)) == ["bare"]
    assert registry.get("bare").aliases == []


@pytest.mark.parametrize("path", ["/nonexistent/path", None])
async def test_load_directory_missing_or_empty_dir_loads_nothing(tmp_path, path):
    assert await SkillRegistry().load_directory(path or str(tmp_path)) == []


async def test_load_directory_skips_skill_files_with_bad_field_types(tmp_path):
    (tmp_path / "good.md").write_text("---\nname: good\naliases: g\n---\n본문")
    (tmp_path / "bad_name.md").write_text("---\nname: 123\n---\n본문")
    (tmp_path / "bad_aliases.yaml").write_text("name: x\naliases: {a: 1}\ncontent: c\n")
    registry = SkillRegistry()

    loaded = await registry.load_directory(str(tmp_path))

    assert loaded == ["good"]
    skill = registry.get("g")
    assert skill is not None and skill.aliases == ["g"]


@pytest.mark.parametrize(
    ("filename", "text"),
    [
        ("list.yaml", "- just\n- a list\n"),
        ("broken.yaml", "name: [unclosed\n"),
        ("content.yaml", "name: c\ncontent: [1, 2]\n"),
        ("desc.md", "---\nname: d\ndescription: [1]\n---\n본문"),
        ("blank.md", "---\nname: '  '\n---\n본문"),
    ],
)
async def test_load_directory_skips_malformed_file_and_logs_it(tmp_path, capsys, filename, text):
    (tmp_path / filename).write_text(text)
    (tmp_path / "ok.md").write_text("---\nname: ok\n---\n본문")
    registry = SkillRegistry()

    loaded = await registry.load_directory(str(tmp_path))

    assert loaded == ["ok"]
    assert f"[SkillRegistry] Failed to load {filename}" in capsys.readouterr().out
