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
