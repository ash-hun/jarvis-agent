"""[common] 설치된 jarvis 패키지의 버전. 버전은 pyproject.toml 한 곳에만 적고 릴리즈 워크플로가 올린다."""

from importlib.metadata import PackageNotFoundError, version

PACKAGE = "jarvis"
UNKNOWN = "0.0.0"


def app_version() -> str:
    """설치 메타데이터의 버전. 설치하지 않고 소스만 돌리면 UNKNOWN."""
    try:
        return version(PACKAGE)
    except PackageNotFoundError:
        return UNKNOWN
