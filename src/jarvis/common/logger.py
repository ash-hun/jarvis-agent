"""[common] 프로젝트 전체의 structlog 로거 설정. 모든 모듈은 get_logger(__name__) 로 받는다."""

import os
import sys
import logging
import structlog
from typing import Any, TextIO
from collections.abc import MutableMapping
from structlog.dev import RichTracebackFormatter
from structlog.tracebacks import ExceptionDictTransformer

ROOT_NAME = "jarvis"
# 레벨은 설정 문서에 이미 있는 키를 쓴다. common 층은 설정 모듈을 import 하지 않아 환경변수로 직접 읽는다
LOG_LEVEL_ENV = "JARVIS_LOG_LEVEL"
LOG_FORMAT_ENV = "LOG_FORMAT"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FORMAT = "console"
REDACTED = "***"
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "api_key",
        "cookie",
        "set-cookie",
        "secret",
    }
)

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


def _mask(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: REDACTED if str(k).lower() in SENSITIVE_KEYS else _mask(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_mask(v) for v in value)
    return value


def _redact(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        event_dict[key] = REDACTED if key.lower() in SENSITIVE_KEYS else _mask(event_dict[key])
    return event_dict


def configure_logging(level: str | None = None, fmt: str | None = None) -> None:
    """jarvis 루트 로거와 structlog 를 한 번만 설정한다. 다시 불려도 핸들러가 늘지 않는다."""
    global _configured
    if _configured:
        return

    level_name = (level or os.environ.get(LOG_LEVEL_ENV) or DEFAULT_LOG_LEVEL).upper()
    fmt_name = (fmt or os.environ.get(LOG_FORMAT_ENV) or DEFAULT_LOG_FORMAT).lower()

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact,
    ]
    # 트레이스백에 지역 변수를 싣지 않는다. 비밀값이 로그로 새는 가장 흔한 경로다
    renderer: list[Any] = (
        [
            structlog.processors.ExceptionRenderer(ExceptionDictTransformer(show_locals=False)),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ]
        if fmt_name == "json"
        else [
            structlog.dev.ConsoleRenderer(
                colors=sys.stdout.isatty(),
                exception_formatter=RichTracebackFormatter(show_locals=False),
            )
        ]
    )

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = _StdoutHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *renderer],
        )
    )
    # 전역 루트가 아니라 jarvis 루트에만 단다. uvicorn 같은 서드파티 로그 출력은 예전 그대로 둔다
    root = logging.getLogger(ROOT_NAME)
    root.handlers = [handler]
    root.setLevel(level_name)
    root.propagate = False
    _configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """name 의 로거를 돌려준다. 설정 전이면 먼저 설정한다."""
    configure_logging()
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger
