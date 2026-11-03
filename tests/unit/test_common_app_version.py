"""common: 설치 메타데이터에서 버전을 읽고, 설치되지 않았으면 기본값을 돌려주는지 검증한다."""

import pytest
from importlib.metadata import PackageNotFoundError

from jarvis.common import app_version as module


def test_app_version_reads_installed_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "version", lambda name: "1.2.3" if name == "jarvis" else "")

    assert module.app_version() == "1.2.3"


def test_app_version_without_install_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> str:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(module, "version", missing)

    assert module.app_version() == module.UNKNOWN
