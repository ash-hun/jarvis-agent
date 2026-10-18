"""parse_startup_plan: CLI 인자를 렌더링 전에 StartupPlan 하나로 정규화한다."""

import pytest

from jarvis.ui.tui.startup import (
    HelpPlan,
    SessionListPlan,
    SessionResumePlan,
    TUIPlan,
    VersionPlan,
    WebPlan,
    parse_startup_plan,
)


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], TUIPlan(kind="tui")),
        (["-h"], HelpPlan(kind="help")),
        (["--help", "--web"], HelpPlan(kind="help")),
        (["-v"], VersionPlan(kind="version")),
        (["--list-sessions"], SessionListPlan(kind="session-list")),
        (["-s", "abc"], SessionResumePlan(kind="session-resume", session_id="abc")),
        (["--web"], WebPlan(kind="web")),
        (
            ["--web", "--session", "s1", "--host", "0.0.0.0", "--port", "8000"],
            WebPlan(kind="web", session_id="s1", host="0.0.0.0", port=8000),
        ),
        (["--unknown", "x"], TUIPlan(kind="tui")),
    ],
)
def test_parse_startup_plan(argv, expected):
    assert parse_startup_plan(argv) == expected


def test_reads_sys_argv_when_none(monkeypatch):
    monkeypatch.setattr("sys.argv", ["jarvis", "--version"])
    assert parse_startup_plan() == VersionPlan(kind="version")


def test_agent_option_starts_tui_with_agent():
    from jarvis.ui.tui.startup import TUIPlan, parse_startup_plan

    assert parse_startup_plan(["--agent", "karen"]) == TUIPlan(kind="tui", session_id=None, agent="karen")
    assert parse_startup_plan([]) == TUIPlan(kind="tui", session_id=None, agent=None)


async def test_resolve_tui_session_uses_agent_default_session_and_stored_agent(tmp_path):
    import pytest
    from types import SimpleNamespace

    from jarvis.agent_layer.session.jsonl import JsonlSessionRepo
    from jarvis.ui.tui.startup import resolve_tui_session

    class _Agents:
        main = SimpleNamespace(agent_id="main")

        def __contains__(self, agent_id):
            return agent_id in ("main", "karen")

        def ids(self):
            return ["main", "karen"]

    repo = JsonlSessionRepo(str(tmp_path))
    assembly = SimpleNamespace(agents=_Agents(), ctx=SimpleNamespace(session_repo=repo))
    assert await resolve_tui_session(assembly, None, None) == ("main", "default")
    assert await resolve_tui_session(assembly, None, "karen") == ("karen", "default-karen")
    # 있는 세션은 저장된 에이전트로 열린다
    assert await resolve_tui_session(assembly, "default-karen", "main") == ("karen", "default-karen")
    with pytest.raises(ValueError):
        await resolve_tui_session(assembly, None, "ghost")
