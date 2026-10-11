"""InfraBuilder 배선: YAML 에이전트 → 에이전트 도구 + orchestrate 도구 + /orchestrate 명령."""

from jarvis.app.infra_builder import build_app
from jarvis.config import JarvisSettings


def test_build_infra_wires_agent_tools_orchestrate_tool_and_slash(monkeypatch, tmp_path):
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "team.yaml").write_text(
        "- name: planner\n  description: 계획\n  level: 0\n"
        "- name: writer\n  description: 작성\n  capabilities: [보고서]\n  level: 1\n  tools: [read_file]\n"
    )
    monkeypatch.setenv("JARVIS_AGENTS__AGENTS_DIR", str(agents))
    monkeypatch.setenv("JARVIS_PROACTIVE__DAEMON_ENABLED", "false")
    monkeypatch.setenv("JARVIS_SCHEDULER__ENABLED", "false")
    monkeypatch.setenv("JARVIS_MEMORY__BACKEND", "in_memory")
    monkeypatch.setenv("JARVIS_SESSION__PERSISTENCE_BACKEND", "jsonl")
    monkeypatch.setenv("JARVIS_SESSION__SESSIONS_DIR", str(tmp_path / "sessions"))

    ctx = build_app(JarvisSettings()).ctx

    names = {t.name for t in ctx.tool_registry.list_all()}
    assert {"agent_planner", "agent_writer", "orchestrate"} <= names
    assert "orchestrate" in ctx.dispatcher.commands
    orchestrate = ctx.tool_registry.get("orchestrate")
    assert "planner" in orchestrate.description and "writer" in orchestrate.description


def test_build_infra_without_agents_has_no_orchestrate(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_AGENTS__AGENTS_DIR", str(tmp_path / "none"))
    monkeypatch.setenv("JARVIS_PROACTIVE__DAEMON_ENABLED", "false")
    monkeypatch.setenv("JARVIS_SCHEDULER__ENABLED", "false")
    monkeypatch.setenv("JARVIS_MEMORY__BACKEND", "in_memory")
    monkeypatch.setenv("JARVIS_SESSION__PERSISTENCE_BACKEND", "jsonl")
    monkeypatch.setenv("JARVIS_SESSION__SESSIONS_DIR", str(tmp_path / "sessions"))

    ctx = build_app(JarvisSettings()).ctx

    assert ctx.tool_registry.get("orchestrate") is None
    assert "orchestrate" not in ctx.dispatcher.commands
