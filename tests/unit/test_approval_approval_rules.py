"""approval: "항상 허용" 패턴 제안과 대조, 규칙 파일의 멱등 저장, 공용과 에이전트별 규칙 겹치기를 검증한다."""

import yaml
import pytest

from jarvis.core.policy.approval_rules import (
    ApprovalRule,
    ApprovalRules,
    LayeredApprovalRules,
    describe,
    rule_matches,
    subject,
    suggest_pattern,
)


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


def test_remove_reports_whether_rule_existed(tmp_path):
    rules = ApprovalRules(str(tmp_path / "a.yaml"))
    rule = ApprovalRule("bash", "ls")
    rules.add(rule)
    assert rules.remove(rule) is True
    assert rules.remove(rule) is False
    assert rules.list() == []


def _layers(tmp_path):
    common = ApprovalRules(str(tmp_path / "approvals.yaml"))
    common.add(ApprovalRule("bash", "git status"))
    karen = LayeredApprovalRules(common, ApprovalRules(str(tmp_path / "approvals" / "karen.yaml")))
    main = LayeredApprovalRules(common, ApprovalRules(str(tmp_path / "approvals" / "main.yaml")))
    return common, karen, main


def test_layered_allows_common_rules_for_every_agent(tmp_path):
    _, karen, main = _layers(tmp_path)
    assert karen.allows("bash", {"command": "git status -s"})
    assert main.allows("bash", {"command": "git status -s"})


def test_layered_always_goes_to_agent_file_only(tmp_path):
    common, karen, main = _layers(tmp_path)
    assert karen.add(ApprovalRule("bash", "uv run")) is True
    assert karen.allows("bash", {"command": "uv run pytest"})
    # 다른 에이전트와 공용 파일에는 번지지 않는다
    assert not main.allows("bash", {"command": "uv run pytest"})
    assert ApprovalRule("bash", "uv run") not in common.list()
    assert yaml.safe_load((tmp_path / "approvals" / "karen.yaml").read_text())["rules"] == [
        {"tool": "bash", "pattern": "uv run"}
    ]
    # 같은 규칙을 다시 더해도, 공용에 있는 규칙을 더해도 파일은 그대로
    assert karen.add(ApprovalRule("bash", "uv run")) is False
    assert karen.add(ApprovalRule("bash", "git status")) is False
    assert karen.list() == [ApprovalRule("bash", "git status"), ApprovalRule("bash", "uv run")]


def test_layered_remove_touches_only_agent_rules(tmp_path):
    common, karen, _ = _layers(tmp_path)
    karen.add(ApprovalRule("bash", "uv run"))
    assert karen.remove(ApprovalRule("bash", "git status")) is False
    assert karen.remove(ApprovalRule("bash", "uv run")) is True
    assert common.list() == [ApprovalRule("bash", "git status")]
