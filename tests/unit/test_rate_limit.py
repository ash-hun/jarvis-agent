"""Rate Limiting — AgentSession._check_rate_limit 단위 테스트."""
from __future__ import annotations

import time
from collections import deque

import pytest

from jarvis.core.policy.pipeline import PolicyDenied


def _make_session() -> object:
    """AgentSession의 _check_rate_limit만 테스트하기 위한 최소 인스턴스."""
    from jarvis.core.session import AgentSession

    session = AgentSession.__new__(AgentSession)
    session._rate_counters = {}
    return session


class TestCheckRateLimit:
    def test_first_request_always_passes(self):
        session = _make_session()
        session._check_rate_limit("user-1", rate_limit=5)

    def test_requests_within_limit_pass(self):
        session = _make_session()
        for _ in range(3):
            session._check_rate_limit("user-1", rate_limit=3)

    def test_exceeding_limit_raises(self):
        session = _make_session()
        for _ in range(3):
            session._check_rate_limit("user-1", rate_limit=3)
        with pytest.raises(PolicyDenied, match="Rate limit exceeded"):
            session._check_rate_limit("user-1", rate_limit=3)

    def test_different_users_are_isolated(self):
        session = _make_session()
        for _ in range(3):
            session._check_rate_limit("user-A", rate_limit=3)
        # user-B는 별도 카운터 — 제한에 걸리지 않음
        session._check_rate_limit("user-B", rate_limit=3)

    def test_old_timestamps_expire_from_window(self):
        session = _make_session()
        # 61초 전 요청 2개를 직접 주입
        old_time = time.monotonic() - 61.0
        session._rate_counters["user-1"] = deque([old_time, old_time])
        # 만료된 항목이 제거되므로 rate_limit=2여도 통과
        session._check_rate_limit("user-1", rate_limit=2)

    def test_error_message_includes_user_id(self):
        session = _make_session()
        for _ in range(1):
            session._check_rate_limit("alice", rate_limit=1)
        with pytest.raises(PolicyDenied, match="alice"):
            session._check_rate_limit("alice", rate_limit=1)
