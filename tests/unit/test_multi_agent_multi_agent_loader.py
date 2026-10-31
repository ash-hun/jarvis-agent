"""multi_agent: 에이전트 YAML 디렉토리를 AgentDefinition 목록으로 읽고 잘못된 정의를 거르는지 검증한다."""

import pytest
import textwrap

from jarvis.core.multi_agent.multi_agent_loader import load_agent_definitions
from jarvis.core.multi_agent.factory import AgentDefinition


def test_load_reads_every_declared_field(tmp_path):
    (tmp_path / "coder.yaml").write_text(
        textwrap.dedent("""\
            name: coder
            description: "Writes code"
            capabilities: [python, bash]
            system_prompt: |
              You are a helpful assistant.
              Be concise.
            tools:
              - read_file
              - bash
            model_override: claude-opus-4-7
            memory:
              stm: per_task
            level: 2
        """)
    )

    [defn] = load_agent_definitions(str(tmp_path))

    assert isinstance(defn, AgentDefinition)
    assert (defn.name, defn.description) == ("coder", "Writes code")
    assert defn.capabilities == ["python", "bash"]
    assert "helpful assistant" in defn.system_prompt
    assert defn.tools == ["read_file", "bash"]
    assert defn.model_override == "claude-opus-4-7"
    assert defn.memory.stm == "per_task"
    assert defn.level == 2


def test_load_fills_defaults_for_omitted_fields(tmp_path):
    (tmp_path / "a.yaml").write_text("name: plain\ndescription: d\nmodel_override: null\n")

    [defn] = load_agent_definitions(str(tmp_path))

    assert defn.model_override is None
    assert defn.memory.stm == "per_parent_session"
    assert defn.level == 0


def test_load_ignores_unknown_fields(tmp_path):
    (tmp_path / "a.yaml").write_text("name: agent\ndescription: Test\nunknown_field: x\nanother_extra: 999\n")

    [defn] = load_agent_definitions(str(tmp_path))

    assert not hasattr(defn, "unknown_field")
    assert not hasattr(defn, "another_extra")


@pytest.mark.parametrize(
    "bad_item",
    [
        "- description: 'no name'",
        "- name: orphan",
        "- name: ''\n  description: desc",
        "- just a string",
        "- 42",
        "- null",
        "- [list]",
        "- name: bad\n  description: d\n  memory:\n    stm: forever",
    ],
)
def test_load_skips_invalid_definition_and_keeps_the_rest(tmp_path, bad_item):
    valid, also = "- name: valid\n  description: ok", "- name: also\n  description: ok"
    (tmp_path / "mixed.yaml").write_text(f"{valid}\n{bad_item}\n{also}\n")

    result = load_agent_definitions(str(tmp_path))

    assert [d.name for d in result] == ["valid", "also"]


@pytest.mark.parametrize("body", ["description: 'no name field'\n", "name: orphan\n", "just text\n"])
def test_load_skips_invalid_single_definition_file(tmp_path, body):
    (tmp_path / "one.yaml").write_text(body)

    assert load_agent_definitions(str(tmp_path)) == []


def test_load_reads_single_and_list_files_in_sorted_order(tmp_path):
    (tmp_path / "z_agent.yaml").write_text("name: z_agent\ndescription: 'Z'\n")
    (tmp_path / "a_team.yaml").write_text("- name: planner\n  description: P\n- name: executor\n  description: E\n")

    result = load_agent_definitions(str(tmp_path))

    assert [d.name for d in result] == ["planner", "executor", "z_agent"]


def test_load_skips_malformed_yaml_file(tmp_path, capsys):
    (tmp_path / "bad.yaml").write_text("name: [unclosed\n")
    (tmp_path / "good.yaml").write_text("name: good\ndescription: 'ok'\n")

    result = load_agent_definitions(str(tmp_path))

    assert [d.name for d in result] == ["good"]
    captured = capsys.readouterr()
    assert "bad.yaml" in captured.out or "Failed" in captured.out


def test_load_ignores_non_yaml_files(tmp_path):
    (tmp_path / "not_yaml.txt").write_text("name: sneaky\ndescription: txt\n")
    (tmp_path / "also_not.json").write_text('{"name": "json_agent"}')
    (tmp_path / "real.yaml").write_text("name: real\ndescription: 'real agent'\n")

    result = load_agent_definitions(str(tmp_path))

    assert [d.name for d in result] == ["real"]


@pytest.mark.parametrize("make_dir", [True, False])
def test_load_returns_empty_for_empty_or_missing_dir(tmp_path, make_dir):
    agents = tmp_path / "agents"
    if make_dir:
        agents.mkdir()

    assert load_agent_definitions(str(agents)) == []


def test_load_expands_tilde(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    agents_dir = tmp_path / ".jarvis" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "home_agent.yaml").write_text("name: home_agent\ndescription: 'from home'\n")

    result = load_agent_definitions("~/.jarvis/agents")

    assert [d.name for d in result] == ["home_agent"]
