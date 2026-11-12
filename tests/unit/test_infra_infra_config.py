"""infra 의 설정: 비어 있는 푸시 키와 DSN 은 백엔드 변수에서 채우고, Infra 전용 값이 있으면 그것이 이긴다."""

from jarvis.infra.infra_config import InfraThresholds, load_config


def test_shared_env_fills_blanks_only(monkeypatch):
    monkeypatch.delenv("JARVIS_INFRA__POSTGRES_DSN", raising=False)
    monkeypatch.setenv("JARVIS_INFRA__VAPID_SUBJECT", "mailto:infra@x")
    env = {"JARVIS_SESSION__POSTGRES_DSN": "postgresql://db", "JARVIS_NOTIFY__WEBPUSH_SUBJECT": "mailto:backend@x",
           "JARVIS_NOTIFY__WEBPUSH_VAPID_PRIVATE_KEY": "pk"}

    cfg = load_config(env)

    assert cfg.postgres_dsn == "postgresql://db" and cfg.vapid_subject == "mailto:infra@x"
    assert cfg.vapid_private_key is not None and cfg.vapid_private_key.get_secret_value() == "pk"


def test_thresholds_map_to_rules_with_active_hours():
    rules = InfraThresholds(active_start_hour=8, active_end_hour=22, fail_streak=5).rules()
    assert rules.active_hours == (8, 22) and rules.fail_streak == 5 and rules.health_fail_count == 3
