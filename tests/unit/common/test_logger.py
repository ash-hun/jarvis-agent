"""get_logger: 핸들러는 jarvis 루트에 한 번만 달리고, 기록 순간의 sys.stdout 으로 메시지만 쓴다."""

import io
import logging
import sys

from jarvis.common.logger import ROOT_NAME, _StdoutHandler, get_logger


def _stdout_handlers() -> list[logging.Handler]:
    return [h for h in logging.getLogger(ROOT_NAME).handlers if isinstance(h, _StdoutHandler)]


def test_handler_is_added_once_across_calls():
    get_logger("jarvis.a")
    get_logger("jarvis.b")
    get_logger("jarvis.a")
    assert len(_stdout_handlers()) == 1
    assert logging.getLogger(ROOT_NAME).propagate is False


def test_writes_message_only_to_current_stdout(monkeypatch):
    logger = get_logger("jarvis.test_logger")
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    logger.info("[Test] hello")
    assert buf.getvalue() == "[Test] hello\n"


def test_follows_stdout_swapped_after_first_call(capsys):
    logger = get_logger("jarvis.test_logger2")
    logger.info("first")
    assert capsys.readouterr().out == "first\n"
    logger.info("second")
    assert capsys.readouterr().out == "second\n"


def test_non_jarvis_names_do_not_get_the_handler(capsys):
    get_logger("other.module").info("x")
    assert capsys.readouterr().out == ""
