"""AgentProfile: 사고 모델은 지정한 항목만 바꾸고, 분류기와 proactivity 팩토리는 켜진 설정에서만 생긴다."""

from unittest.mock import MagicMock

from pydantic import SecretStr

from jarvis.app.agent_profile import MAIN_AGENT_ID, AgentProfile
from jarvis.config import JarvisSettings
from jarvis.model_layer.types import ModelConfig

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


def test_reply_classifier_uses_thought_model():
    classifier = _profile(model="haiku").reply_classifier()
    assert classifier is not None
    assert classifier._model.model == "haiku"


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
