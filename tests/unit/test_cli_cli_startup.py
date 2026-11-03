"""cli 의 startup: CLI 인자를 StartupPlan 하나로 정규화하고 시작 세션과 에이전트를 고른다."""

import pytest
from types import SimpleNamespace

from jarvis.ui.cli.cli_startup import (
    HelpPlan,
    WebPlan,
    VersionPlan,
    SessionListPlan,
    parse_startup_plan,
    resolve_start_session,
)
from jarvis.agent_layer.session.jsonl import JsonlSessionRepo


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], WebPlan(kind="web")),
        (["--web"], WebPlan(kind="web")),
        (["-h"], HelpPlan(kind="help")),
        (["--help", "--web"], HelpPlan(kind="help")),
        (["-v"], VersionPlan(kind="version")),
        (["--list-sessions"], SessionListPlan(kind="session-list")),
        (
            ["--session", "s1", "--host", "0.0.0.0", "--port", "8000"],
            WebPlan(kind="web", session_id="s1", host="0.0.0.0", port=8000),
        ),
        (["-a", "karen"], WebPlan(kind="web", agent="karen")),
        (["--unknown", "x"], WebPlan(kind="web")),
    ],
)
def test_parse_startup_plan_normalizes_argv(argv, expected):
    assert parse_startup_plan(argv) == expected


def test_parse_startup_plan_reads_sys_argv_when_none(monkeypatch):
    monkeypatch.setattr("sys.argv", ["jarvis", "--version"])

    assert parse_startup_plan() == VersionPlan(kind="version")


class _Agents:
    main = SimpleNamespace(agent_id="main")

    def __contains__(self, agent_id):  # type: ignore[no-untyped-def]
        return agent_id in ("main", "karen")

    def ids(self):  # type: ignore[no-untyped-def]
        return ["main", "karen"]


async def test_resolve_start_session_uses_agent_default_session_and_stored_agent(tmp_path):
    repo = JsonlSessionRepo(str(tmp_path))
    assembly = SimpleNamespace(agents=_Agents(), ctx=SimpleNamespace(session_repo=repo))

    assert await resolve_start_session(assembly, None, None) == ("main", "default")
    assert await resolve_start_session(assembly, None, "karen") == ("karen", "default-karen")
    assert await resolve_start_session(assembly, "default-karen", "main") == ("karen", "default-karen")


async def test_resolve_start_session_rejects_unknown_agent(tmp_path):
    assembly = SimpleNamespace(agents=_Agents(), ctx=SimpleNamespace(session_repo=JsonlSessionRepo(str(tmp_path))))

    with pytest.raises(ValueError):
        await resolve_start_session(assembly, None, "ghost")
