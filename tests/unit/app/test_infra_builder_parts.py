"""InfraBuilder 의 기능별 build_* 를 따로 부른다: 모델 설정, 기본 도구, 성찰 트리거 모드."""

import pytest

from jarvis.core.proactive import ActivityClock, AnyTrigger, ExternalTrigger, IdleTrigger, IntervalTrigger
from jarvis.app.infra_builder import InfraBuilder
from jarvis.config import JarvisSettings


def _builder(**proactive: object) -> InfraBuilder:
    settings = JarvisSettings()
    for k, v in proactive.items():
        setattr(settings.proactive, k, v)
    return InfraBuilder(settings)


def test_build_model_config_copies_llm_settings():
    settings = JarvisSettings()
    m = InfraBuilder(settings).build_model_config()
    llm = settings.llm
    assert (m.provider, m.model, m.base_url, m.temperature, m.max_tokens) == (
        llm.provider, llm.model, llm.base_url, llm.temperature, llm.max_tokens,
    )


def test_build_tool_registry_has_builtin_tools():
    names = {t.name for t in _builder().build_tool_registry().list_all()}
    assert {"bash", "read_file", "write_file", "edit_file", "glob", "grep", "list_dir"} <= names


def test_build_tool_registry_twice_gives_same_tool_names():
    builder = _builder()
    first = sorted(t.name for t in builder.build_tool_registry().list_all())
    assert first == sorted(t.name for t in builder.build_tool_registry().list_all())


def test_agent_tools_are_kept_out_of_the_app_registry():
    builder = _builder()
    agent_only = {t.name for t in builder.build_agent_tools().list_all()}
    assert agent_only == {"lh_notice", "sh_notice", "housing_loan", "housing_budget"}
    assert not agent_only & {t.name for t in builder.build_tool_registry().list_all()}


@pytest.mark.parametrize(
    ("mode", "kind"),
    [("interval", IntervalTrigger), ("idle", IdleTrigger), ("both", AnyTrigger)],
)
def test_build_reflection_trigger_modes(mode, kind):
    trigger = _builder(daemon_trigger=mode).build_reflection_trigger(ActivityClock())
    assert isinstance(trigger, kind)


def test_both_mode_combines_interval_and_idle():
    trigger = _builder(daemon_trigger="both").build_reflection_trigger(ActivityClock())
    assert [type(t) for t in trigger._triggers] == [IntervalTrigger, IdleTrigger]


def test_external_trigger_is_combined_with_any_mode():
    external = ExternalTrigger()
    trigger = _builder(daemon_trigger="idle").build_reflection_trigger(ActivityClock(), external)
    assert isinstance(trigger, AnyTrigger)
    assert isinstance(trigger._triggers[0], IdleTrigger) and trigger._triggers[1] is external


def test_build_notifier_none_without_channel():
    assert _builder().build_notifier() is None
