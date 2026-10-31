"""agent_registry: 정의 파일이 에이전트가 되고 비운 항목은 main 을 이어받으며 도구 경계가 지켜지는지 검증한다."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from jarvis.app.agent_registry import AgentRegistry, load_agent_specs, profile_from_spec
from jarvis.app.agent_profile import ANSWER_RULE, MAIN_AGENT_ID, AgentProfile
from jarvis.core.policy.approval_rules import ApprovalRule, ApprovalRules
from tests.fixtures.agent_registry_helpers import app_tools
from jarvis.core.tools.tools_registry import ToolRegistry
from jarvis.model_layer.model_types import ModelConfig
from jarvis.core.proactive import FeedbackLearner
from jarvis.jarvis_config import JarvisSettings
from jarvis.app.app_context import AppContext

TEAM_DIR = Path(__file__).parents[2] / "team"
MAIN = ModelConfig(provider="ollama", model="gemma", api_key=None, base_url="http://x")
KAREN = """
name: K.A.R.E.N.
description: 정보 수집
palette:
  primary: "#97BC62"
system_prompt: 당신은 카렌입니다.
model: gemma-small
tools: [web_search, read_file]
proactive: false
"""
BOUNDED = """
name: K.A.R.E.N.
tools: [lh_notice, housing_profile, read_file, schedule]
boundaries:
  ask: [housing_profile]
  never: [read_file]
"""


def _main() -> AgentProfile:
    return AgentProfile.main(JarvisSettings(), MAIN, MagicMock())


def _bounded_registry(tmp_path, spec: str = BOUNDED) -> AgentRegistry:
    (tmp_path / "karen.yaml").write_text(spec)
    tools = app_tools("lh_notice", "housing_profile", "read_file", "schedule", "bash")
    ctx = AppContext(session_repo=MagicMock(), tool_registry=tools, settings=JarvisSettings())
    ctx.agent_tools = ToolRegistry()
    return AgentRegistry.load(ctx, MagicMock(), _main(), str(tmp_path))


def test_spec_file_becomes_profile_on_top_of_main(tmp_path):
    (tmp_path / "karen.yaml").write_text(KAREN)
    specs = load_agent_specs(str(tmp_path))
    main = _main()

    karen = profile_from_spec("karen", specs["karen"], main)

    assert karen.agent_id == "karen" and karen.name == "K.A.R.E.N."
    assert karen.brand.palette.primary == "#97BC62"
    # 정하지 않은 색은 기본 팔레트
    assert karen.brand.palette.background == main.brand.palette.background
    # 모델은 이름만 바뀌고 프로바이더와 주소는 main 것
    assert (karen.model.provider, karen.model.model, karen.model.base_url) == ("ollama", "gemma-small", "http://x")
    assert karen.tools == ("web_search", "read_file")
    assert karen.system_prompt == f"당신은 카렌입니다.\n\n{ANSWER_RULE}"
    assert karen.proactive.enabled is False
    assert karen.thought is main.thought
    # 피드백 학습은 에이전트마다 따로
    assert karen.feedback_learner is not main.feedback_learner


def test_unset_fields_inherit_main(tmp_path):
    (tmp_path / "scout.yaml").write_text("name: SCOUT\n")
    main = _main()
    scout = profile_from_spec("scout", load_agent_specs(str(tmp_path))["scout"], main)
    assert scout.model is main.model
    assert scout.proactive is main.proactive
    assert scout.tools == () and scout.system_prompt == ANSWER_RULE


@pytest.mark.parametrize("filename", ["main.yaml", "Bad Name.yaml", "9lives.yaml"])
def test_reserved_or_invalid_ids_are_skipped(tmp_path, filename):
    (tmp_path / filename).write_text("name: X\n")
    assert load_agent_specs(str(tmp_path)) == {}


def test_broken_file_skips_only_itself(tmp_path):
    (tmp_path / "karen.yaml").write_text(KAREN)
    (tmp_path / "typo.yaml").write_text("name: T\nunknown_field: 1\n")
    (tmp_path / "noname.yaml").write_text("description: 이름 없음\n")
    assert list(load_agent_specs(str(tmp_path))) == ["karen"]


def test_missing_dir_means_main_only(tmp_path):
    ctx = AppContext(session_repo=MagicMock(), tool_registry=MagicMock(), settings=JarvisSettings())
    registry = AgentRegistry.load(ctx, MagicMock(), _main(), str(tmp_path / "none"))
    assert registry.ids() == [MAIN_AGENT_ID]
    assert registry.main.is_main


def test_registry_keeps_main_first_and_builds_per_agent(tmp_path):
    (tmp_path / "karen.yaml").write_text(KAREN)
    ctx = AppContext(session_repo=MagicMock(), tool_registry=MagicMock(), settings=JarvisSettings())
    registry = AgentRegistry.load(ctx, MagicMock(), _main(), str(tmp_path))

    assert registry.ids() == ["main", "karen"]
    assert "karen" in registry and "ghost" not in registry
    assert registry.builder("karen").profile is registry.get("karen")
    assert registry.get("ghost") is None
    with pytest.raises(KeyError):
        registry.builder("ghost")


def test_registry_rejects_non_main_first():
    ctx = AppContext(session_repo=MagicMock(), tool_registry=MagicMock(), settings=JarvisSettings())
    karen = AgentProfile(
        agent_id="karen", brand=MagicMock(), model=MAIN, thought=MagicMock(), proactive=MagicMock(),
        feedback_learner=MagicMock(),
    )
    with pytest.raises(ValueError):
        AgentRegistry(ctx, MagicMock(), [karen])


def test_repo_team_karen_has_her_own_persona_and_keeps_her_rules():
    """저장소의 team/karen.yaml 이 실제로 읽힌다(docker 가 이 디렉터리를 쓴다)."""
    main = AgentProfile.main(JarvisSettings(), ModelConfig(provider="faux", model="m"), FeedbackLearner())
    specs = load_agent_specs(str(TEAM_DIR))

    karen = profile_from_spec("karen", specs["karen"], main)

    assert main.system_prompt is not None and "J.A.R.V.I.S." in main.system_prompt
    assert karen.system_prompt is not None and karen.system_prompt.startswith("너는 애쉬의 유능한")
    assert "housing_budget" in karen.system_prompt and "J.A.R.V.I.S." not in karen.system_prompt
    assert karen.brand.persona != main.brand.persona


def test_approval_rules_are_per_agent_and_cached(tmp_path):
    settings = JarvisSettings()
    settings.security.agent_approvals_dir = str(tmp_path / "approvals")
    common = ApprovalRules(str(tmp_path / "approvals.yaml"))
    services = MagicMock()
    services.approval_rules = common
    ctx = AppContext(session_repo=MagicMock(), tool_registry=MagicMock(), settings=settings)
    (tmp_path / "team").mkdir()
    (tmp_path / "team" / "karen.yaml").write_text(KAREN)
    registry = AgentRegistry.load(ctx, services, _main(), str(tmp_path / "team"))

    karen = registry.approval_rules("karen")
    assert registry.approval_rules("karen") is karen
    karen.add(ApprovalRule("bash", "ls"))
    assert (tmp_path / "approvals" / "karen.yaml").exists()
    assert not registry.approval_rules("main").allows("bash", {"command": "ls"})


def test_spec_boundaries_reach_the_profile(tmp_path):
    (tmp_path / "karen.yaml").write_text(BOUNDED)

    karen = profile_from_spec("karen", load_agent_specs(str(tmp_path))["karen"], _main())

    assert (karen.ask_tools, karen.never_tools) == (("housing_profile",), ("read_file",))


@pytest.mark.parametrize(
    ("spec", "hidden", "visible"),
    [
        (BOUNDED, "read_file", {"lh_notice", "housing_profile", "schedule"}),
        ("name: SCOUT\nboundaries:\n  never: [bash]\n", "bash", {"lh_notice"}),
    ],
    ids=["listed_tools", "whole_app_registry"],
)
def test_never_tools_are_not_visible(tmp_path, spec, hidden, visible):
    names = {t.name for t in _bounded_registry(tmp_path, spec).builder("karen").tool_registry().list_all()}

    assert hidden not in names and visible <= names


def test_task_agent_carries_ask_tools(tmp_path):
    agent = _bounded_registry(tmp_path).task_agent("karen")

    assert agent is not None and agent.ask_tools == ("housing_profile",)
