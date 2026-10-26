"""InfraBuilder 의 기능별 build_* 를 따로 부른다: 모델 설정, 기본 도구, 성찰 트리거 모드."""

import pytest

from jarvis.core.proactive import ActivityClock, AnyTrigger, ExternalTrigger, IdleTrigger, IntervalTrigger
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.memory_service import MemoryService
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
    assert agent_only == {"lh_notice", "sh_notice", "housing_loan", "housing_budget", "housing_watch"}
    assert not agent_only & {t.name for t in builder.build_tool_registry().list_all()}
    # 사용자 기억이 있어야 주거 프로필 도구가 생긴다
    with_memory = {t.name for t in builder.build_agent_tools(MemoryService(InMemoryItemStore())).list_all()}
    assert with_memory == agent_only | {"housing_profile"}


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


async def test_build_notifier_sends_to_slack_and_discord(monkeypatch):
    from pydantic import SecretStr

    sent: list[str] = []

    async def fake_post(url, body):
        sent.append(url)
        return 204

    monkeypatch.setattr("jarvis.core.notify.slack.post_json", fake_post)
    monkeypatch.setattr("jarvis.core.notify.discord.post_json", fake_post)
    builder = _builder()
    builder._settings.notify.slack_webhook_url = SecretStr("https://hooks.slack.com/x")
    builder._settings.notify.discord_webhook_url = SecretStr("https://discord.com/api/webhooks/1/t")
    notify = builder.build_notifier()
    assert notify is not None
    await notify({"type": "reminder", "name": "n", "text": "t"})
    assert sent == ["https://hooks.slack.com/x", "https://discord.com/api/webhooks/1/t"]


def test_agent_identities_use_brand_names_and_avatar_folder(tmp_path):
    (tmp_path / "karen.yaml").write_text("name: K.A.R.E.N.\npalette:\n  primary: \"#97BC62\"\n", encoding="utf-8")
    builder = _builder()
    builder._settings.team.dir = str(tmp_path)
    builder._settings.notify.avatar_base_url = "https://cdn.example/avatars/"
    identities = builder.agent_identities()
    assert identities["karen"] == ("K.A.R.E.N.", "https://cdn.example/avatars/karen.png", "#97BC62")
    main_brand = builder._settings.brand
    assert identities["main"] == (main_brand.name, "https://cdn.example/avatars/main.png", main_brand.palette.primary)
    builder._settings.notify.avatar_base_url = ""
    assert builder.agent_identities()["karen"][:2] == ("K.A.R.E.N.", "")
