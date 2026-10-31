"""에이전트 개성: 말투가 시스템 프롬프트 앞과 사고 모델 프롬프트에 같이 들어간다."""

from jarvis.agent_layer.thought.prompt import DEFAULT_REFLECTION_TEMPLATE, DEFAULT_TEMPLATE, ThoughtPromptTemplate
from jarvis.app.agent_registry import load_agent_specs, profile_from_spec
from jarvis.app.agent_profile import ANSWER_RULE, compose_system_prompt


def test_persona_comes_before_the_work_instructions_and_every_agent_gets_the_answer_rule():
    assert compose_system_prompt("차분하게", "lh_notice 로") == f"차분하게\n\nlh_notice 로\n\n{ANSWER_RULE}"
    assert compose_system_prompt("차분하게", None) == f"차분하게\n\n{ANSWER_RULE}"
    assert compose_system_prompt("", "  ") == ANSWER_RULE


def test_both_thought_templates_have_a_persona_slot():
    for text in (DEFAULT_TEMPLATE, DEFAULT_REFLECTION_TEMPLATE):
        rendered = ThoughtPromptTemplate(text).render(persona="다정한 말투")
        assert "[말투] 다정한 말투" in rendered and "{{persona}}" not in rendered


def test_karen_has_her_own_persona_and_keeps_her_rules(monkeypatch):
    from jarvis.model_layer.model_types import ModelConfig
    from jarvis.app.agent_profile import AgentProfile
    from jarvis.core.proactive import FeedbackLearner
    from jarvis.jarvis_config import JarvisSettings

    settings = JarvisSettings()
    main = AgentProfile.main(settings, ModelConfig(provider="faux", model="m"), FeedbackLearner())
    karen = profile_from_spec("karen", load_agent_specs("team")["karen"], main)
    assert main.system_prompt is not None and "J.A.R.V.I.S." in main.system_prompt
    assert karen.system_prompt is not None and karen.system_prompt.startswith("너는 애쉬의 유능한")
    assert "housing_budget" in karen.system_prompt and "J.A.R.V.I.S." not in karen.system_prompt
    assert karen.brand.persona != main.brand.persona
