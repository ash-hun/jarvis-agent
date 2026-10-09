"""승인 기억. 사용자가 "항상 허용"한 (도구, 패턴) 규칙을 YAML 에 쌓고, 같은 패턴의 호출은 다시 묻지 않는다."""

import fnmatch
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = "~/.jarvis/approvals.yaml"
PREFIX_WORDS = 2  # bash 는 앞 두 단어까지를 패턴으로 제안한다 (`git status` → `git status …` 전부)
PATH_PARAM_TOOLS = frozenset({"write_file", "edit_file", "read_file"})
ANY = "*"


@dataclass(frozen=True)
class ApprovalRule:
    tool: str
    pattern: str


def subject(tool: str, params: dict[str, Any]) -> str:
    """패턴과 대조할 문자열. bash 는 명령, 파일 도구는 경로, 그 외는 빈 문자열(도구 단위 규칙만 가능)."""
    if tool == "bash":
        return str(params.get("command", ""))
    if tool in PATH_PARAM_TOOLS:
        return str(params.get("path", ""))
    return ""


def tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def suggest_pattern(tool: str, params: dict[str, Any]) -> str:
    """이 호출을 "항상 허용"할 때 저장할 패턴. 결정적이라 같은 호출은 같은 패턴을 낳는다."""
    text = subject(tool, params)
    if tool == "bash":
        head = tokens(text)[:PREFIX_WORDS]
        return " ".join(head) if head else ANY
    if tool in PATH_PARAM_TOOLS and text:
        return f"{Path(text).parent}/*"
    return ANY


def rule_matches(rule: ApprovalRule, tool: str, params: dict[str, Any]) -> bool:
    """bash 패턴은 토큰 접두(`git status` 는 `git status --short` 를 덮는다), 경로 패턴은 glob."""
    if rule.tool != tool:
        return False
    if rule.pattern == ANY:
        return True
    text = subject(tool, params)
    if tool == "bash":
        want = tokens(rule.pattern)
        return bool(want) and tokens(text)[: len(want)] == want
    return fnmatch.fnmatchcase(text, rule.pattern)


def describe(tool: str, params: dict[str, Any]) -> str:
    """승인 화면에 보여 줄 한 줄. bash 는 명령 그대로, 나머지는 도구와 인자."""
    if tool == "bash":
        return subject(tool, params)
    text = subject(tool, params)
    return f"{tool} {text}".strip() if text else f"{tool} {params}"


class ApprovalRules:
    """규칙 파일 하나를 소유한다. 같은 규칙을 두 번 더해도 파일은 한 줄이다."""

    def __init__(self, path: str = DEFAULT_PATH) -> None:
        self._path = Path(path).expanduser()
        self._rules: list[ApprovalRule] = self._load()

    def _load(self) -> list[ApprovalRule]:
        if not self._path.exists():
            return []
        data = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        rows = (data.get("rules") or []) if isinstance(data, dict) else []
        return [
            ApprovalRule(tool=str(r["tool"]), pattern=str(r["pattern"]))
            for r in rows
            if isinstance(r, dict) and r.get("tool") and r.get("pattern")
        ]

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"rules": [{"tool": r.tool, "pattern": r.pattern} for r in self._rules]}
        tmp = self._path.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
        os.replace(tmp, self._path)  # 쓰다 죽어도 반쪽 파일이 남지 않는다

    def list(self) -> list[ApprovalRule]:
        return list(self._rules)

    def allows(self, tool: str, params: dict[str, Any]) -> bool:
        return any(rule_matches(r, tool, params) for r in self._rules)

    def add(self, rule: ApprovalRule) -> bool:
        """새로 더해졌으면 True. 이미 있으면 파일을 건드리지 않고 False."""
        if rule in self._rules:
            return False
        self._rules.append(rule)
        self._save()
        return True

    def remove(self, rule: ApprovalRule) -> bool:
        if rule not in self._rules:
            return False
        self._rules.remove(rule)
        self._save()
        return True
