"""에이전트 개성: 말투가 시스템 프롬프트 앞과 사고 모델 프롬프트에 같이 들어간다."""

from jarvis.agent_layer.thought.prompt import DEFAULT_REFLECTION_TEMPLATE, DEFAULT_TEMPLATE, ThoughtPromptTemplate
from jarvis.app.agent_registry import load_agent_specs, profile_from_spec
from jarvis.app.agent_profile import compose_system_prompt


def test_persona_comes_before_the_work_instructions():
    assert compose_system_prompt("차분하게", "공고는 lh_notice 로") == "차분하게\n\n공고는 lh_notice 로"
    assert compose_system_prompt("차분하게", None) == "차분하게"
    assert compose_system_prompt("", "  ") is None


def test_both_thought_templates_have_a_persona_slot():
    for text in (DEFAULT_TEMPLATE, DEFAULT_REFLECTION_TEMPLATE):
        rendered = ThoughtPromptTemplate(text).render(persona="다정한 말투")
        assert "[말투] 다정한 말투" in rendered and "{{persona}}" not in rendered


def test_karen_has_her_own_persona_and_keeps_her_rules(monkeypatch):
    from jarvis.app.agent_profile import AgentProfile
    from jarvis.core.proactive import FeedbackLearner
    from jarvis.model_layer.types import ModelConfig
    from jarvis.config import JarvisSettings

    settings = JarvisSettings()
    main = AgentProfile.main(settings, ModelConfig(provider="faux", model="m"), FeedbackLearner())
    karen = profile_from_spec("karen", load_agent_specs("team")["karen"], main)
    assert main.system_prompt is not None and "J.A.R.V.I.S." in main.system_prompt
    assert karen.system_prompt is not None and karen.system_prompt.startswith("너는 피터 파커 슈트의 AI K.A.R.E.N.")
    assert "housing_budget" in karen.system_prompt and "J.A.R.V.I.S." not in karen.system_prompt
    assert karen.brand.persona != main.brand.persona
