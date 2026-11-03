"""settings 의 overlay: 비밀값 가림, 허용 목록 patch 합치기, settings.yaml 의 멱등 쓰기."""

import yaml
import pytest
from pydantic import ValidationError

from jarvis.app.settings_overlay import (
    MASK,
    VoicePatch,
    SettingsPatch,
    ProactivePatch,
    SettingsOverlay,
    merge_patch,
    mask_secrets,
    editable_values,
)
from jarvis.ui.web.router.settings_router import pending_changes
from jarvis.jarvis_config import JarvisSettings


def test_mask_secrets_hides_secret_named_values_and_keeps_empty_ones():
    masked = mask_secrets({
        "llm": {"api_key": "sk-1", "model": "m", "max_tokens": 9},
        "security": {"api_keys": {"k": {}}},
        "notify": {"slack_webhook_url": "https://hooks", "discord_bot_token": "t"},
        "x": {"postgres_dsn": ""},
    })

    assert masked == {
        "llm": {"api_key": MASK, "model": "m", "max_tokens": 9},
        "security": {"api_keys": MASK},
        "notify": {"slack_webhook_url": MASK, "discord_bot_token": MASK},
        "x": {"postgres_dsn": ""},
    }


def test_masked_effective_settings_contain_no_secret_value(monkeypatch):
    monkeypatch.setenv("JARVIS_LLM__API_KEY", "sk-secret-123")

    dumped = str(mask_secrets(JarvisSettings().model_dump(mode="json")))

    assert "sk-secret-123" not in dumped


def test_merge_patch_overlays_only_given_fields_and_is_idempotent():
    stored = {"voice": {"stt_provider": "whisper"}, "llm": {"model": "m"}}
    patch = SettingsPatch(voice=VoicePatch(wake_threshold=0.7))

    once = merge_patch(stored, patch)

    assert once == {"voice": {"stt_provider": "whisper", "wake_threshold": 0.7}, "llm": {"model": "m"}}
    assert merge_patch(once, patch) == once
    assert stored == {"voice": {"stt_provider": "whisper"}, "llm": {"model": "m"}}


def test_settings_patch_rejects_unknown_field_and_out_of_range_value():
    with pytest.raises(ValidationError):
        SettingsPatch.model_validate({"llm": {"api_key": "x"}})
    with pytest.raises(ValidationError):
        ProactivePatch(daemon_interval_sec=5)


def test_overlay_apply_writes_once_then_reports_no_change(tmp_path):
    path = tmp_path / "sub" / "settings.yaml"
    overlay = SettingsOverlay(path)
    patch = SettingsPatch(voice=VoicePatch(stt_provider="whisper"))

    assert overlay.apply(patch) is True
    first = path.read_text()
    assert overlay.apply(patch) is False
    assert path.read_text() == first
    assert yaml.safe_load(first) == {"voice": {"stt_provider": "whisper"}}
    assert list(path.parent.iterdir()) == [path]


def test_overlay_read_treats_missing_or_non_mapping_file_as_empty(tmp_path):
    path = tmp_path / "settings.yaml"
    assert SettingsOverlay(path).read() == {}
    path.write_text("- a\n- b\n")
    assert SettingsOverlay(path).read() == {}


def test_editable_values_and_pending_changes_follow_allowlist():
    editable = editable_values(JarvisSettings())

    assert set(editable) == {"voice", "proactive", "thought", "focus"}
    assert "api_key" not in editable["thought"]
    current = editable["voice"]["wake_threshold"]
    stored = {"voice": {"wake_threshold": current, "stt_provider": "zzz", "unknown": 1}}
    assert pending_changes(stored, editable) == {"voice": {"stt_provider": "zzz"}}


def test_editable_fields_follow_patch_schema_with_enum_and_range():
    from jarvis.app.settings_overlay import editable_fields

    fields = editable_fields()

    assert fields["voice"]["stt_provider"]["enum"] == ["browser", "whisper"]
    assert (fields["voice"]["wake_threshold"]["minimum"], fields["voice"]["wake_threshold"]["maximum"]) == (0.05, 0.99)
    assert fields["focus"] == {"enabled": {"title": "Enabled", "type": "boolean"}}
    assert set(fields) == set(editable_values(JarvisSettings()))
