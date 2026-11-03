"""[scripts] 커밋 제목으로 다음 릴리즈 버전을 정하고, 버전이 적힌 파일들을 그 버전으로 맞춘다."""

import re
import sys
import json
import argparse
import subprocess
from pathlib import Path
from collections.abc import Callable

ROOT = Path(__file__).resolve().parents[1]
# 커밋 제목 머리말(`Feat:`, `Fix(voice):`, `Feat!:`). 대소문자는 가리지 않는다
SUBJECT = re.compile(r"^(?P<kind>[A-Za-z]+)(?:\([^)]*\))?(?P<breaking>!)?:")
MINOR_KINDS = {"feat"}
# 이것만 있으면 사용자에게 달라진 게 없어 릴리즈하지 않는다
SKIP_KINDS = {"docs", "test", "tests", "chore", "ci", "style", "build", "release"}
PYPROJECT_VERSION = re.compile(r'(?m)^version = "[^"]+"')
LOCK_VERSION = re.compile(r'(?m)^(name = "jarvis"\nversion = )"[^"]+"')
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def bump_of(subject: str) -> str | None:
    """커밋 제목 하나가 요구하는 올림(major, minor, patch). 릴리즈할 게 없는 제목이면 None."""
    m = SUBJECT.match(subject.strip())
    if not m:
        return "patch"
    if m["breaking"] or "BREAKING CHANGE" in subject:
        return "major"
    kind = m["kind"].lower()
    if kind in SKIP_KINDS:
        return None
    return "minor" if kind in MINOR_KINDS else "patch"


def next_version(current: str, subjects: list[str]) -> str | None:
    """지금 버전과 지난 릴리즈 뒤 커밋 제목들로 다음 버전. 올릴 게 없으면 None."""
    if not SEMVER.match(current):
        raise ValueError(f"semver 가 아닌 버전: {current}")
    bumps = {b for b in map(bump_of, subjects) if b}
    major, minor, patch = map(int, current.split("."))
    if "major" in bumps:
        return f"{major + 1}.0.0"
    if "minor" in bumps:
        return f"{major}.{minor + 1}.0"
    if "patch" in bumps:
        return f"{major}.{minor}.{patch + 1}"
    return None


def current_version(root: Path = ROOT) -> str:
    m = re.search(r'(?m)^version = "([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"))
    if not m:
        raise ValueError("pyproject.toml 에 version 이 없다")
    return m[1]


def apply_version(version: str, root: Path = ROOT) -> list[str]:
    """버전이 적힌 파일을 version 으로 맞추고 바뀐 파일 목록을 돌려준다. 이미 그 버전이면 아무 파일도 쓰지 않는다."""
    if not SEMVER.match(version):
        raise ValueError(f"semver 가 아닌 버전: {version}")
    changed: list[str] = []

    def rewrite(rel: str, update: Callable[[str], str]) -> None:
        path = root / rel
        before = path.read_text(encoding="utf-8")
        after = update(before)
        if after != before:
            path.write_text(after, encoding="utf-8")
            changed.append(rel)

    rewrite("pyproject.toml", lambda t: PYPROJECT_VERSION.sub(f'version = "{version}"', t, count=1))
    rewrite("uv.lock", lambda t: LOCK_VERSION.sub(rf'\g<1>"{version}"', t, count=1))
    rewrite("desktop/package.json", lambda t: _json_version(t, version, lock=False))
    rewrite("desktop/package-lock.json", lambda t: _json_version(t, version, lock=True))
    return changed


def _json_version(text: str, version: str, lock: bool) -> str:
    data = json.loads(text)
    data["version"] = version
    if lock:
        data["packages"][""]["version"] = version
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def commit_subjects(since: str | None) -> list[str]:
    """since(태그) 뒤의 커밋 제목. 태그가 없으면 처음부터. 머지 커밋은 빼고 그 안의 커밋을 본다."""
    rev = f"{since}..HEAD" if since else "HEAD"
    out = subprocess.run(
        ["git", "log", "--no-merges", "--format=%s", rev], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    plan = sub.add_parser("plan", help="다음 버전을 출력한다. 올릴 게 없으면 빈 줄")
    plan.add_argument("--since", default="", help="지난 릴리즈 태그. 비우면 처음부터")
    apply = sub.add_parser("apply", help="버전 파일을 그 버전으로 맞춘다")
    apply.add_argument("version")
    args = parser.parse_args(argv)
    if args.cmd == "plan":
        print(next_version(current_version(), commit_subjects(args.since or None)) or "")
        return 0
    for rel in apply_version(args.version):
        print(rel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
