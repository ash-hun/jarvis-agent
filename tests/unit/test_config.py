"""config.py — Pydantic Settings 로딩 테스트."""
from __future__ import annotations

import os

import pytest

from jarvis.config import JarvisSettings, get_settings, reset_settings


def test_default_settings(monkeypatch):
    monkeypatch.delenv("JARVIS_LLM__PROVIDER", raising=False)
    monkeypatch.delenv("JARVIS_LLM__MODEL", raising=False)
    monkeypatch.delenv("JARVIS_SECURITY__REQUIRE_AUTH", raising=False)
    monkeypatch.delenv("JARVIS_MEMORY__BACKEND", raising=False)
    monkeypatch.delenv("JARVIS_DEBUG", raising=False)
    settings = JarvisSettings()
    assert settings.llm.provider == "anthropic"
    assert settings.llm.model == "claude-sonnet-4-5"
    assert settings.security.require_auth is True
    assert settings.memory.backend == "postgres"
    assert settings.debug is False


def test_env_override(monkeypatch):
    monkeypatch.setenv("JARVIS_LLM__PROVIDER", "openai")
    monkeypatch.setenv("JARVIS_LLM__MODEL", "gpt-4o")
    monkeypatch.setenv("JARVIS_DEBUG", "true")

    settings = JarvisSettings()
    assert settings.llm.provider == "openai"
    assert settings.llm.model == "gpt-4o"
    assert settings.debug is True


def test_get_settings_singleton(monkeypatch):
    monkeypatch.setenv("JARVIS_LLM__PROVIDER", "anthropic")
    reset_settings()
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_reset_settings(monkeypatch):
    monkeypatch.setenv("JARVIS_LLM__PROVIDER", "anthropic")
    reset_settings()
    s1 = get_settings()
    reset_settings()
    s2 = get_settings()
    assert s1 is not s2


def test_api_key_is_secret(monkeypatch):
    monkeypatch.setenv("JARVIS_LLM__PROVIDER", "anthropic")
    monkeypatch.setenv("JARVIS_LLM__API_KEY", "sk-secret-key-123")
    settings = JarvisSettings()
    assert settings.llm.api_key is not None
    assert settings.llm.api_key.get_secret_value() == "sk-secret-key-123"
    assert "sk-secret" not in str(settings.llm.api_key)


def test_security_config_defaults(monkeypatch):
    monkeypatch.setenv("JARVIS_LLM__PROVIDER", "anthropic")
    settings = JarvisSettings()
    assert "user" in settings.security.allowed_roles
    assert settings.security.input_max_length == 10_000
    assert len(settings.security.dangerous_commands) > 0


def test_brand_defaults():
    settings = JarvisSettings()
    assert settings.brand.name == "J.A.R.V.I.S."
    assert settings.brand.quote == "Proof the Heart"
    assert settings.brand.palette.primary == "#5fc8e2"
    assert len(settings.brand.palette.nebula) == 3


def test_brand_env_override(monkeypatch):
    monkeypatch.setenv("JARVIS_BRAND__NAME", "F.R.I.D.A.Y.")
    monkeypatch.setenv("JARVIS_BRAND__PALETTE__PRIMARY", "#ff7a45")
    monkeypatch.setenv("JARVIS_BRAND__PALETTE__NEBULA", '["#ff4b2b", "#ffb347"]')
    settings = JarvisSettings()
    assert settings.brand.name == "F.R.I.D.A.Y."
    assert settings.brand.palette.primary == "#ff7a45"
    assert settings.brand.palette.nebula == ["#ff4b2b", "#ffb347"]


def test_brand_rejects_non_hex_color(monkeypatch):
    from pydantic import ValidationError

    monkeypatch.setenv("JARVIS_BRAND__PALETTE__PRIMARY", "cyan")
    with pytest.raises(ValidationError):
        JarvisSettings()
