"""release: 커밋 제목에서 다음 버전을 정하는 규칙과 버전 파일 맞추기를 검증한다."""

import json
import pytest
from pathlib import Path
from scripts.release_version import apply_version, bump_of, next_version


@pytest.mark.parametrize(
    ("subject", "bump"),
    [
        ("Feat: FLOW 화면을 더한다 (#207)", "minor"),
        ("fix(voice): 말 끝을 잡는다", "patch"),
        ("Refactor: 설정을 나눈다", "patch"),
        ("Feat!: 설정 파일 형식을 바꾼다", "major"),
        ("Docs: 문서를 고친다", None),
        ("Release: v0.2.0", None),
        ("머리말 없는 커밋", "patch"),
    ],
)
def test_bump_of_reads_subject_prefix(subject: str, bump: str | None) -> None:
    assert bump_of(subject) == bump


def test_next_version_takes_largest_bump() -> None:
    assert next_version("0.1.3", ["Fix: a", "Feat: b", "Docs: c"]) == "0.2.0"
    assert next_version("0.2.0", ["Fix: a"]) == "0.2.1"
    assert next_version("0.2.1", ["Feat!: a", "Feat: b"]) == "1.0.0"


def test_next_version_without_user_facing_change_is_none() -> None:
    assert next_version("0.2.0", ["Docs: a", "Chore: b"]) is None
    assert next_version("0.2.0", []) is None


def test_next_version_rejects_non_semver() -> None:
    with pytest.raises(ValueError):
        next_version("0.2", ["Feat: a"])


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "desktop").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "jarvis"\nversion = "0.1.0"\n\n[tool.x]\nversion = "9.9.9"\n', encoding="utf-8"
    )
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "httpx"\nversion = "0.27.0"\n\n[[package]]\nname = "jarvis"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "desktop/package.json").write_text(
        json.dumps({"name": "jarvis-desktop", "version": "0.1.0"}, indent=2) + "\n", encoding="utf-8"
    )
    lock = {"name": "jarvis-desktop", "version": "0.1.0", "packages": {"": {"version": "0.1.0"}}}
    (tmp_path / "desktop/package-lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return tmp_path


def test_apply_version_rewrites_only_project_versions(tmp_path: Path) -> None:
    root = _repo(tmp_path)

    changed = apply_version("0.2.0", root)

    assert sorted(changed) == ["desktop/package-lock.json", "desktop/package.json", "pyproject.toml", "uv.lock"]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.2.0"' in pyproject and 'version = "9.9.9"' in pyproject
    lock = (root / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "httpx"\nversion = "0.27.0"' in lock and 'name = "jarvis"\nversion = "0.2.0"' in lock
    assert json.loads((root / "desktop/package-lock.json").read_text())["packages"][""]["version"] == "0.2.0"


def test_apply_version_twice_writes_nothing_the_second_time(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    apply_version("0.2.0", root)

    assert apply_version("0.2.0", root) == []
