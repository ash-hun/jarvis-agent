"""get_logger: jarvis 루트에 핸들러 하나, 기록 순간의 sys.stdout 으로 출력, json 형식과 비밀값 마스킹."""

import io
import sys
import json
import pytest
import logging

from jarvis.common.logger import ROOT_NAME, _StdoutHandler, get_logger
from jarvis.common import logger as logger_module


def _stdout_handlers() -> list[logging.Handler]:
    return [h for h in logging.getLogger(ROOT_NAME).handlers if isinstance(h, _StdoutHandler)]


@pytest.fixture
def json_format(monkeypatch):
    monkeypatch.setattr(logger_module, "_configured", False)
    logger_module.configure_logging(fmt="json")
    yield
    logger_module._configured = False
    logger_module.configure_logging(fmt="console")


def test_handler_is_added_once_across_calls():
    get_logger("jarvis.a")
    get_logger("jarvis.b")
    get_logger("jarvis.a")
    logger_module.configure_logging()
    assert len(_stdout_handlers()) == 1
    assert logging.getLogger(ROOT_NAME).propagate is False


def test_writes_to_current_stdout(monkeypatch):
    logger = get_logger("jarvis.test_logger")
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    logger.info("[Test] hello")
    assert "[Test] hello" in buf.getvalue()


def test_follows_stdout_swapped_after_first_call(capsys):
    logger = get_logger("jarvis.test_logger2")
    logger.info("first")
    assert "first" in capsys.readouterr().out
    logger.info("second")
    out = capsys.readouterr().out
    assert "second" in out and "first" not in out


def test_non_jarvis_names_do_not_get_the_handler(capsys):
    get_logger("other.module").info("x")
    assert capsys.readouterr().out == ""


def test_json_format_emits_one_object_per_line_and_masks_secrets(json_format, capsys):
    get_logger("jarvis.test_json").info("login", api_key="sk-live", user="ash")
    record = json.loads(capsys.readouterr().out.strip())
    assert record["event"] == "login" and record["level"] == "info" and record["logger"] == "jarvis.test_json"
    assert record["api_key"] == "***" and record["user"] == "ash"
