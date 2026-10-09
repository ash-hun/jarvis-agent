"""_build_thought (startup) 단위 테스트 — A1 모델 분리 / A2 싱크 / A3 composer."""

from __future__ import annotations

from types import SimpleNamespace

from jarvis.agent_layer.thought import (
    DefaultThoughtComposer,
    InterpretationOnlyComposer,
)
from jarvis.config import JarvisSettings
from jarvis.memory.manager import MemoryManager
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.model_layer.types import ModelConfig
from jarvis.ui.tui.startup import AppContext, _build_thought


def _ctx(**thought_overrides) -> AppContext:
    settings = JarvisSettings()
    settings.thought.enabled = True
    for k, v in thought_overrides.items():
        setattr(settings.thought, k, v)
    return AppContext(session_repo=None, tool_registry=None, settings=settings)


def _extra() -> dict:
    return {
        "memory_chain": SimpleNamespace(retrieve=lambda *a, **k: []),
        "memory": MemoryManager(InMemoryItemStore()),
    }


_MAIN = ModelConfig(provider="anthropic", model="claude", api_key="mainkey", base_url="")


def test_disabled_returns_all_none():
    settings = JarvisSettings()
    settings.thought.enabled = False  # 명시적으로 끔
    ctx = AppContext(session_repo=None, tool_registry=None, settings=settings)
    assert _build_thought(ctx, _extra(), _MAIN) == (None, None, None)


# ── A1: 사고 모델 provider/key/base_url 분리 ──────────────────────────────────


def test_thought_model_inherits_main_when_unset():
    engine, _, _ = _build_thought(_ctx(), _extra(), _MAIN)
    assert engine._model.provider == "anthropic"
    assert engine._model.model == "claude"
    assert engine._model.api_key == "mainkey"


def test_thought_model_fully_separated():
    from pydantic import SecretStr

    engine, _, _ = _build_thought(
        _ctx(
            provider="ollama",
            model="llama3",
            base_url="http://localhost:11434",
            api_key=SecretStr("thoughtkey"),
        ),
        _extra(),
        _MAIN,
    )
    assert engine._model.provider == "ollama"
    assert engine._model.model == "llama3"
    assert engine._model.base_url == "http://localhost:11434"
    assert engine._model.api_key == "thoughtkey"


def test_thought_model_partial_override_keeps_main_key():
    # provider/model만 바꾸고 키는 비우면 메인 키 상속.
    engine, _, _ = _build_thought(_ctx(provider="ollama", model="llama3"), _extra(), _MAIN)
    assert engine._model.provider == "ollama"
    assert engine._model.api_key == "mainkey"


# ── A2: log_sinks 선택 ────────────────────────────────────────────────────────


def test_default_sink_is_ltm_only():
    _, log, _ = _build_thought(_ctx(), _extra(), _MAIN)
    assert len(log._sinks) == 1


def test_both_sinks_selected():
    _, log, _ = _build_thought(_ctx(log_sinks=["ltm", "stm"]), _extra(), _MAIN)
    assert len(log._sinks) == 2


def test_unknown_sink_ignored():
    _, log, _ = _build_thought(_ctx(log_sinks=["ltm", "bogus"]), _extra(), _MAIN)
    assert len(log._sinks) == 1


# ── A3: composer 선택 ─────────────────────────────────────────────────────────


def test_default_composer_selected():
    _, _, composer = _build_thought(_ctx(), _extra(), _MAIN)
    assert isinstance(composer, DefaultThoughtComposer)


def test_interpretation_only_composer_selected():
    _, _, composer = _build_thought(_ctx(composer="interpretation_only"), _extra(), _MAIN)
    assert isinstance(composer, InterpretationOnlyComposer)


def test_unknown_composer_falls_back_to_default():
    _, _, composer = _build_thought(_ctx(composer="nope"), _extra(), _MAIN)
    assert isinstance(composer, DefaultThoughtComposer)
