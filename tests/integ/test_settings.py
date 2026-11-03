"""settings 기능: 조회는 비밀값을 가리고, 편집은 허용 목록만 settings.yaml 에 저장해 다음 기동에 반영된다."""

import pytest

pytest.importorskip("fastapi")

from tests.fixtures.web_hud_helpers import web_assembly, web_client  # noqa: E402
from jarvis.jarvis_config import JarvisSettings  # noqa: E402


@pytest.fixture
def settings_file(monkeypatch, tmp_path):
    path = tmp_path / "settings.yaml"
    monkeypatch.setenv("JARVIS_SETTINGS_FILE", str(path))
    return path


@pytest.fixture
def client(monkeypatch, tmp_path, settings_file):
    with web_client(web_assembly(monkeypatch, tmp_path, LLM__API_KEY="sk-hidden-42")) as c:
        yield c


def test_health_and_settings_view_mask_secrets(client):
    health = client.get("/api/health").json()
    assert health["ok"] is True and health["version"].count(".") == 2
    body = client.get("/api/settings").json()

    assert "sk-hidden-42" not in str(body)
    assert body["effective"]["llm"]["api_key"] == "***"
    assert body["pending"] == {}


def test_put_settings_saves_pending_value_and_next_boot_applies_it(client, settings_file):
    payload = {"voice": {"wake_threshold": 0.77}, "proactive": {"daemon_trigger": "idle"}}

    first = client.put("/api/settings", json=payload).json()
    again = client.put("/api/settings", json=payload).json()

    assert first["changed"] is True and again["changed"] is False
    assert first["pending"] == {"voice": {"wake_threshold": 0.77}, "proactive": {"daemon_trigger": "idle"}}
    rebooted = JarvisSettings()
    assert (rebooted.voice.wake_threshold, rebooted.proactive.daemon_trigger) == (0.77, "idle")


def test_put_settings_rejects_field_outside_allowlist(client, settings_file):
    response = client.put("/api/settings", json={"llm": {"api_key": "x"}})

    assert response.status_code == 422
    assert not settings_file.exists()
