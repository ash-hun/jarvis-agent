"""[common] 프로젝트 전체의 로거 설정. 모든 모듈은 get_logger(__name__) 로 받는다."""

import sys
import logging
from typing import TextIO

# print 시절과 같은 출력: 표준 출력에 메시지만. "[Thought] ..." 같은 접두는 메시지가 갖고 있다
LOG_FORMAT = "%(message)s"
ROOT_NAME = "jarvis"

_configured: bool = False


class _StdoutHandler(logging.StreamHandler):  # type: ignore[type-arg]  # StreamHandler 의 제네릭 인자는 런타임에 없다
    """기록할 때마다 그 순간의 sys.stdout 에 쓴다. 테스트가 stdout 을 바꿔 끼워도 따라간다."""

    def __init__(self) -> None:
        super().__init__(sys.stdout)

    @property
    def stream(self) -> TextIO:
        return sys.stdout

    @stream.setter
    def stream(self, _value: TextIO) -> None:
        pass


def get_logger(name: str) -> logging.Logger:
    """name 의 로거를 돌려준다. 첫 호출에서만 jarvis 루트 로거에 핸들러를 단다(다시 불러도 중복되지 않음)."""
    global _configured
    if not _configured:
        root = logging.getLogger(ROOT_NAME)
        handler = _StdoutHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        root.propagate = False
        _configured = True
    return logging.getLogger(name)
