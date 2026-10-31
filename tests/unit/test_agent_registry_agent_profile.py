"""agent_registry: 시스템 프롬프트 조립, 사고 모델 상속, 분류기와 proactivity 팩토리 생성 조건을 검증한다."""

import pytest
from pydantic import SecretStr
from unittest.mock import MagicMock

from jarvis.app.agent_profile import ANSWER_RULE, MAIN_AGENT_ID, AgentProfile, compose_system_prompt
from tests.fixtures.agent_loop_helpers import ScriptedProvider, register, text_turn
from jarvis.model_layer.model_types import ModelConfig
from jarvis.jarvis_config import JarvisSettings

MAIN = ModelConfig(provider="anthropic", model="claude", api_key="mainkey", base_url="https://main", temperature=0.3,
                   max_tokens=123)


def _profile(thought_enabled: bool = True, proactive_enabled: bool = True, **thought: object) -> AgentProfile:
    settings = JarvisSettings()
    settings.thought.enabled = thought_enabled
    settings.proactive.enabled = proactive_enabled
    for k, v in thought.items():
        setattr(settings.thought, k, v)
    learner = MagicMock()
    learner.threshold = lambda: 0.5
    return AgentProfile.main(settings, MAIN, learner)


@pytest.mark.parametrize(
    ("persona", "instructions", "expected"),
    [
        ("차분하게", "lh_notice 로", f"차분하게\n\nlh_notice 로\n\n{ANSWER_RULE}"),
        ("차분하게", None, f"차분하게\n\n{ANSWER_RULE}"),
        ("", "  ", ANSWER_RULE),
    ],
)
def test_persona_comes_before_work_instructions_and_answer_rule_is_always_last(persona, instructions, expected):
    assert compose_system_prompt(persona, instructions) == expected


def test_main_uses_main_agent_id_and_settings_parts():
    settings = JarvisSettings()
    profile = AgentProfile.main(settings, MAIN, MagicMock())
    assert profile.agent_id == MAIN_AGENT_ID == "main"
    assert profile.brand == settings.brand
    assert profile.model is MAIN


def test_thought_model_inherits_everything_when_unset():
    m = _profile(provider="", model="", api_key=None, base_url="").thought_model()
    assert (m.provider, m.model, m.api_key, m.base_url) == ("anthropic", "claude", "mainkey", "https://main")
    assert (m.temperature, m.max_tokens) == (0.3, 123)


def test_thought_model_overrides_only_given_fields():
    m = _profile(model="haiku", api_key=SecretStr("tkey")).thought_model()
    assert (m.provider, m.model, m.api_key, m.base_url) == ("anthropic", "haiku", "tkey", "https://main")


def test_reply_classifier_none_when_thought_disabled():
    assert _profile(thought_enabled=False).reply_classifier() is None


async def test_reply_classifier_asks_the_thought_model():
    seen: list[str] = []

    class Recording(ScriptedProvider):
        async def stream(self, model, context, options=None):
            seen.append(model.model)
            async for event in super().stream(model, context, options):
                yield event

    provider_name = register(Recording([text_turn('{"verdict": "accept"}')])).provider
    classifier = _profile(provider=provider_name, model="haiku").reply_classifier()
    assert classifier is not None

    await classifier.classify("feedback", "좋아")

    assert seen == ["haiku"]


def test_proactivity_factory_none_unless_proactive_and_thought():
    assert _profile(thought_enabled=False).proactivity_factory() is None
    assert _profile(proactive_enabled=False).proactivity_factory() is None
    assert _profile(thought_enabled=False, proactive_enabled=False).proactivity_factory() is None


def test_proactivity_factory_binds_emit_and_learner_threshold():
    from jarvis.core.proactive import DefaultProactivityCore

    factory = _profile().proactivity_factory()
    assert factory is not None

    async def emit(_msg: object) -> None:
        return None

    core = factory(emit)
    assert isinstance(core, DefaultProactivityCore)
    assert core._emit is emit
    assert core._policy._threshold_provider() == 0.5
