"""승인 기억: 패턴 제안과 대조, 규칙 파일의 멱등 저장, sandbox.authorize 의 결정 순서."""

import pytest
import yaml

from jarvis.core.policy.approval_rules import (
    ApprovalRule,
    ApprovalRules,
    describe,
    rule_matches,
    subject,
    suggest_pattern,
)
from jarvis.core.policy.sandbox import DefaultSandbox, PermissiveSandbox

# ── 순수 함수 ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("tool", "params", "pattern"),
    [
        ("bash", {"command": "git status --short"}, "git status"),
        ("bash", {"command": "ls"}, "ls"),
        ("bash", {"command": ""}, "*"),
        ("bash", {"command": "echo 'unterminated"}, "echo 'unterminated"),  # shlex 실패 시 공백 분리로 폴백
        ("write_file", {"path": "src/app/main.py", "content": "x"}, "src/app/*"),
        ("edit_file", {"path": "/tmp/notes.md"}, "/tmp/*"),
        ("web_search", {"query": "x"}, "*"),
    ],
)
def test_suggest_pattern_is_deterministic(tool, params, pattern):
    assert suggest_pattern(tool, params) == pattern
    assert suggest_pattern(tool, params) == suggest_pattern(tool, params)


@pytest.mark.parametrize(
    ("rule", "tool", "params", "matches"),
    [
        (ApprovalRule("bash", "git status"), "bash", {"command": "git status --short"}, True),
        (ApprovalRule("bash", "git status"), "bash", {"command": "git statusx"}, False),  # 토큰 접두. 문자열 접두 아님
        (ApprovalRule("bash", "git status"), "bash", {"command": "git stash"}, False),
        (ApprovalRule("bash", "git status"), "write_file", {"path": "git status"}, False),  # 도구가 다르면 무관
        (ApprovalRule("bash", "*"), "bash", {"command": "rm -rf /tmp/x"}, True),
        (ApprovalRule("write_file", "src/app/*"), "write_file", {"path": "src/app/main.py"}, True),
        (ApprovalRule("write_file", "src/app/*"), "write_file", {"path": "src/other/main.py"}, False),
        (ApprovalRule("web_search", "*"), "web_search", {"query": "x"}, True),
    ],
)
def test_rule_matches(rule, tool, params, matches):
    assert rule_matches(rule, tool, params) is matches


def test_subject_and_describe():
    assert subject("bash", {"command": "ls -la"}) == "ls -la"
    assert describe("bash", {"command": "ls -la"}) == "ls -la"
    assert describe("write_file", {"path": "a.txt", "content": "..."}) == "write_file a.txt"
    assert describe("web_search", {"query": "q"}).startswith("web_search ")


# ── 규칙 파일 ─────────────────────────────────────────────────────────────────


def test_add_is_idempotent_and_persists(tmp_path):
    path = tmp_path / "nested" / "approvals.yaml"
    rules = ApprovalRules(str(path))
    rule = ApprovalRule("bash", "git status")

    assert rules.add(rule) is True
    assert rules.add(rule) is False  # 두 번째는 파일을 건드리지 않는다
    assert yaml.safe_load(path.read_text()) == {"rules": [{"tool": "bash", "pattern": "git status"}]}

    reloaded = ApprovalRules(str(path))
    assert reloaded.list() == [rule]
    assert reloaded.allows("bash", {"command": "git status -s"}) is True
    assert reloaded.allows("bash", {"command": "git push"}) is False


def test_missing_or_malformed_file_yields_no_rules(tmp_path):
    assert ApprovalRules(str(tmp_path / "none.yaml")).list() == []
    bad = tmp_path / "bad.yaml"
    bad.write_text("rules:\n  - tool: bash\n  - nope\n")  # pattern 없는 행과 비 dict 행은 버린다
    assert ApprovalRules(str(bad)).list() == []


def test_remove(tmp_path):
    rules = ApprovalRules(str(tmp_path / "a.yaml"))
    rule = ApprovalRule("bash", "ls")
    rules.add(rule)
    assert rules.remove(rule) is True
    assert rules.remove(rule) is False
    assert rules.list() == []


# ── sandbox.authorize ─────────────────────────────────────────────────────────


class _Recorder:
    def __init__(self, answer):
        self.answer = answer
        self.calls: list[tuple[str, str, str]] = []

    async def __call__(self, command, reason, always_pattern):
        self.calls.append((command, reason, always_pattern))
        return self.answer


async def test_authorize_skips_tools_that_need_no_approval(tmp_path):
    cb = _Recorder(False)
    sandbox = DefaultSandbox(require_approval_for=["bash"], approval_callback=cb)
    assert await sandbox.authorize("read_file", {"path": "x"}) is True
    assert cb.calls == []


async def test_authorize_asks_and_allows_once_without_saving_rule(tmp_path):
    rules = ApprovalRules(str(tmp_path / "a.yaml"))
    cb = _Recorder(True)
    sandbox = DefaultSandbox(require_approval_for=["bash"], approval_callback=cb, approval_rules=rules)

    assert await sandbox.authorize("bash", {"command": "git status"}) is True
    assert cb.calls == [("git status", "Tool 'bash' requires approval", "git status")]
    assert rules.list() == []  # 이번 한 번이지 규칙이 아니다

    assert await sandbox.authorize("bash", {"command": "git status"}) is True
    assert len(cb.calls) == 2  # 다시 묻는다


async def test_authorize_always_saves_rule_then_stops_asking(tmp_path):
    rules = ApprovalRules(str(tmp_path / "a.yaml"))
    cb = _Recorder("always")
    sandbox = DefaultSandbox(require_approval_for=["bash"], approval_callback=cb, approval_rules=rules)

    assert await sandbox.authorize("bash", {"command": "uv run pytest -q"}) is True
    assert rules.list() == [ApprovalRule("bash", "uv run")]

    cb.answer = False  # 이제 콜백이 거부해도 규칙이 먼저 통과시킨다
    assert await sandbox.authorize("bash", {"command": "uv run ruff check"}) is True
    assert len(cb.calls) == 1

    assert await sandbox.authorize("bash", {"command": "rm -rf build"}) is False  # 다른 패턴은 여전히 묻는다
    assert len(cb.calls) == 2


async def test_authorize_without_rules_store_treats_always_as_allow_once(tmp_path):
    cb = _Recorder("always")
    sandbox = DefaultSandbox(require_approval_for=["bash"], approval_callback=cb)
    assert await sandbox.authorize("bash", {"command": "ls"}) is True
    assert cb.calls[0][2] == ""  # 저장소가 없으면 "항상" 패턴을 제안하지 않는다


async def test_authorize_denies_without_callback():
    sandbox = DefaultSandbox(require_approval_for=["bash"])
    assert await sandbox.authorize("bash", {"command": "ls"}) is False


async def test_permissive_sandbox_authorizes_everything():
    assert await PermissiveSandbox().authorize("bash", {"command": "rm -rf /"}) is True
