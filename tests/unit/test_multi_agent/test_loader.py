"""YAML 기반 AgentDefinition 로더 테스트."""

from __future__ import annotations

import textwrap

from jarvis.core.multi_agent.factory import AgentDefinition
from jarvis.core.multi_agent.loader import _parse_definition, load_agent_definitions

# ---------------------------------------------------------------------------
# _parse_definition 단위 테스트
# ---------------------------------------------------------------------------


class TestParseDefinition:
    def test_valid_minimal(self):
        data = {"name": "researcher", "description": "Does research"}
        defn = _parse_definition(data)
        assert defn is not None
        assert defn.name == "researcher"
        assert defn.description == "Does research"

    def test_valid_full(self):
        data = {
            "name": "coder",
            "description": "Writes code",
            "capabilities": ["python", "bash"],
            "system_prompt": "You are a coder.",
            "tools": ["read_file", "bash"],
            "model_override": "claude-opus-4-7",
        }
        defn = _parse_definition(data)
        assert defn is not None
        assert defn.capabilities == ["python", "bash"]
        assert defn.system_prompt == "You are a coder."
        assert defn.tools == ["read_file", "bash"]
        assert defn.model_override == "claude-opus-4-7"

    def test_missing_name_returns_none(self):
        assert _parse_definition({"description": "No name"}) is None

    def test_missing_description_returns_none(self):
        assert _parse_definition({"name": "nameless"}) is None

    def test_empty_name_returns_none(self):
        assert _parse_definition({"name": "", "description": "desc"}) is None

    def test_non_dict_returns_none(self):
        assert _parse_definition("string") is None
        assert _parse_definition(42) is None
        assert _parse_definition(None) is None
        assert _parse_definition(["list"]) is None

    def test_unknown_fields_filtered(self):
        data = {
            "name": "agent",
            "description": "Test",
            "unknown_field": "should_be_ignored",
            "another_extra": 999,
        }
        defn = _parse_definition(data)
        assert defn is not None
        assert not hasattr(defn, "unknown_field")
        assert not hasattr(defn, "another_extra")

    def test_returns_agent_definition_instance(self):
        defn = _parse_definition({"name": "x", "description": "y"})
        assert isinstance(defn, AgentDefinition)

    def test_model_override_null(self):
        data = {"name": "a", "description": "b", "model_override": None}
        defn = _parse_definition(data)
        assert defn is not None
        assert defn.model_override is None


# ---------------------------------------------------------------------------
# load_agent_definitions 통합 테스트
# ---------------------------------------------------------------------------


class TestLoadAgentDefinitions:
    def test_nonexistent_dir_returns_empty(self, tmp_path):
        result = load_agent_definitions(str(tmp_path / "does_not_exist"))
        assert result == []

    def test_empty_dir_returns_empty(self, tmp_path):
        result = load_agent_definitions(str(tmp_path))
        assert result == []

    def test_single_agent_yaml(self, tmp_path):
        (tmp_path / "researcher.yaml").write_text(
            textwrap.dedent("""\
                name: researcher
                description: "Does research"
                tools:
                  - web_search
            """)
        )
        result = load_agent_definitions(str(tmp_path))
        assert len(result) == 1
        assert result[0].name == "researcher"
        assert result[0].tools == ["web_search"]

    def test_list_yaml_loads_multiple(self, tmp_path):
        (tmp_path / "team.yaml").write_text(
            textwrap.dedent("""\
                - name: planner
                  description: "Plans tasks"
                - name: executor
                  description: "Executes tasks"
                  tools:
                    - bash
            """)
        )
        result = load_agent_definitions(str(tmp_path))
        assert len(result) == 2
        names = {d.name for d in result}
        assert names == {"planner", "executor"}

    def test_multiple_yaml_files(self, tmp_path):
        (tmp_path / "a.yaml").write_text("name: agent_a\ndescription: 'A'\n")
        (tmp_path / "b.yaml").write_text("name: agent_b\ndescription: 'B'\n")
        result = load_agent_definitions(str(tmp_path))
        assert len(result) == 2

    def test_files_loaded_in_sorted_order(self, tmp_path):
        (tmp_path / "z_agent.yaml").write_text("name: z_agent\ndescription: 'Z'\n")
        (tmp_path / "a_agent.yaml").write_text("name: a_agent\ndescription: 'A'\n")
        result = load_agent_definitions(str(tmp_path))
        assert result[0].name == "a_agent"
        assert result[1].name == "z_agent"

    def test_malformed_yaml_skipped(self, tmp_path, capsys):
        (tmp_path / "bad.yaml").write_text("name: [unclosed\n")
        (tmp_path / "good.yaml").write_text("name: good\ndescription: 'ok'\n")
        result = load_agent_definitions(str(tmp_path))
        # malformed file skipped, good file loaded
        assert len(result) == 1
        assert result[0].name == "good"
        captured = capsys.readouterr()
        assert "bad.yaml" in captured.out or "Failed" in captured.out

    def test_yaml_missing_name_skipped(self, tmp_path):
        (tmp_path / "no_name.yaml").write_text("description: 'no name field'\n")
        result = load_agent_definitions(str(tmp_path))
        assert result == []

    def test_yaml_missing_description_skipped(self, tmp_path):
        (tmp_path / "no_desc.yaml").write_text("name: orphan\n")
        result = load_agent_definitions(str(tmp_path))
        assert result == []

    def test_system_prompt_loaded(self, tmp_path):
        (tmp_path / "with_prompt.yaml").write_text(
            textwrap.dedent("""\
                name: agent_with_prompt
                description: "Has a system prompt"
                system_prompt: |
                  You are a helpful assistant.
                  Be concise.
            """)
        )
        result = load_agent_definitions(str(tmp_path))
        assert len(result) == 1
        assert "helpful assistant" in result[0].system_prompt

    def test_model_override_loaded(self, tmp_path):
        (tmp_path / "with_model.yaml").write_text(
            textwrap.dedent("""\
                name: powerful_agent
                description: "Uses opus"
                model_override: claude-opus-4-7
            """)
        )
        result = load_agent_definitions(str(tmp_path))
        assert result[0].model_override == "claude-opus-4-7"

    def test_non_yaml_files_ignored(self, tmp_path):
        (tmp_path / "not_yaml.txt").write_text("name: sneaky\ndescription: txt\n")
        (tmp_path / "also_not.json").write_text('{"name": "json_agent"}')
        (tmp_path / "real.yaml").write_text("name: real\ndescription: 'real agent'\n")
        result = load_agent_definitions(str(tmp_path))
        assert len(result) == 1
        assert result[0].name == "real"

    def test_list_with_invalid_item_skipped(self, tmp_path):
        (tmp_path / "mixed.yaml").write_text(
            textwrap.dedent("""\
                - name: valid_agent
                  description: "Valid"
                - description: "Missing name — should be skipped"
                - name: also_valid
                  description: "Also valid"
            """)
        )
        result = load_agent_definitions(str(tmp_path))
        assert len(result) == 2
        names = {d.name for d in result}
        assert names == {"valid_agent", "also_valid"}

    def test_tilde_path_expanded(self, monkeypatch, tmp_path):
        """~ が실제 존재하지 않아도 expanduser 호출이 일어나는지 확인."""
        monkeypatch.setenv("HOME", str(tmp_path))
        agents_dir = tmp_path / ".jarvis" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "home_agent.yaml").write_text(
            "name: home_agent\ndescription: 'from home'\n"
        )
        result = load_agent_definitions("~/.jarvis/agents")
        assert len(result) == 1
        assert result[0].name == "home_agent"
