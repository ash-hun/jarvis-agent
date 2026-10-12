"""AgentRegistry: 정의 파일 한 장이 최상위 에이전트 하나가 되고, 비운 항목은 main 을 이어받는다."""

from unittest.mock import MagicMock

import pytest

from jarvis.app.agent_profile import MAIN_AGENT_ID, AgentProfile
from jarvis.app.agent_registry import AgentRegistry, load_agent_specs, profile_from_spec
from jarvis.app.app_context import AppContext
from jarvis.config import JarvisSettings
from jarvis.model_layer.types import ModelConfig

MAIN = ModelConfig(provider="ollama", model="gemma", api_key=None, base_url="http://x")
KAREN = """
name: K.A.R.E.N.
description: 정보 수집
palette:
  primary: "#f0607c"
system_prompt: 당신은 카렌입니다.
model: gemma-small
tools: [web_search, read_file]
proactive: false
"""


def _main() -> AgentProfile:
    return AgentProfile.main(JarvisSettings(), MAIN, MagicMock())


def test_spec_file_becomes_profile_on_top_of_main(tmp_path):
    (tmp_path / "karen.yaml").write_text(KAREN)
    specs = load_agent_specs(str(tmp_path))
    main = _main()

    karen = profile_from_spec("karen", specs["karen"], main)

    assert karen.agent_id == "karen" and karen.name == "K.A.R.E.N."
    assert karen.brand.palette.primary == "#f0607c"
    # 정하지 않은 색은 기본 팔레트
    assert karen.brand.palette.background == main.brand.palette.background
    # 모델은 이름만 바뀌고 프로바이더와 주소는 main 것
    assert (karen.model.provider, karen.model.model, karen.model.base_url) == ("ollama", "gemma-small", "http://x")
    assert karen.tools == ("web_search", "read_file")
    assert karen.system_prompt == "당신은 카렌입니다."
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
    assert scout.tools == () and scout.system_prompt is None


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


def test_repo_team_karen_definition_is_valid():
    """저장소의 team/karen.yaml 이 실제로 읽힌다(docker 가 이 디렉터리를 쓴다)."""
    from pathlib import Path

    team = Path(__file__).parents[3] / "team"
    assert "karen" in load_agent_specs(str(team))
