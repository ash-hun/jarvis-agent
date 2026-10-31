"""policy 기능: 접근 키가 /api, /ws 를 지키고 사용자가 식별되며, 세션이 사용자별 60초 rate limit 을 거는지 검증한다."""

import time
import pytest
from types import SimpleNamespace

pytest.importorskip("fastapi")

from starlette.websockets import WebSocketDisconnect  # noqa: E402

from jarvis.core.policy.pipeline import AuthContext, PolicyDenied, PolicyResult, SecurityPipeline  # noqa: E402
from tests.fixtures.web_hud_helpers import web_assembly, web_client  # noqa: E402
from jarvis.core.policy.authenticator import ApiKeyAuthenticator  # noqa: E402
from jarvis.core.policy.validator import DefaultInputValidator  # noqa: E402
from jarvis.core.policy.sandbox import PermissiveSandbox  # noqa: E402
from jarvis.core.policy.policy import AllowAllPolicy  # noqa: E402
from jarvis.core.session import AgentSession  # noqa: E402
import jarvis.core.session as session_module  # noqa: E402


KEY = "test-key-abc"


@pytest.fixture
def auth_client(monkeypatch, tmp_path):
    keys = f'{{"{KEY}": {{"name": "jh", "roles": ["admin"]}}}}'
    with web_client(web_assembly(monkeypatch, tmp_path, SECURITY__API_KEYS=keys)) as c:
        yield c


@pytest.mark.parametrize(
    ("url", "headers", "code"),
    [
        ("/api/sessions", {}, 401),
        ("/api/sessions", {"Authorization": "Bearer wrong"}, 401),
        ("/api/sessions", {"Authorization": f"Bearer {KEY}"}, 200),
        (f"/api/sessions?token={KEY}", {}, 200),
        ("/", {}, 200),
        ("/brand.js", {}, 200),
    ],
)
def test_api_requires_key_but_static_shell_stays_open(auth_client, url, headers, code):
    resp = auth_client.get(url, headers=headers)

    assert resp.status_code == code


def test_ws_without_key_is_closed_with_4401(auth_client):
    with pytest.raises(WebSocketDisconnect) as exc, auth_client.websocket_connect("/ws?session_id=default") as ws:
        ws.receive_json()

    assert exc.value.code == 4401


def test_ws_with_key_identifies_user_through_a_turn(auth_client, faux_model_with_response):
    faux_model_with_response("ok")

    with auth_client.websocket_connect(f"/ws?session_id=default&token={KEY}") as ws:
        hello = ws.receive_json()
        ws.send_json({"type": "user_message", "text": "안녕"})
        seen = []
        for _ in range(20):
            seen.append(ws.receive_json()["type"])
            if seen[-1] == "agent_end":
                break

    assert hello["type"] == "connected" and hello["user"] == "jh"
    assert "agent_end" in seen


def test_open_mode_connected_payload_has_no_user(monkeypatch, tmp_path):
    client = web_client(web_assembly(monkeypatch, tmp_path))
    with client, client.websocket_connect("/ws?session_id=default") as ws:
        hello = ws.receive_json()

    assert hello["user"] is None


KEYS = {"key-alice": "alice", "key-bob": "bob"}


class LimitedPolicy(AllowAllPolicy):
    def __init__(self, rate_limit: int) -> None:
        self._rate_limit = rate_limit

    async def check(self, auth_ctx: AuthContext, requested_tools: list[str]) -> PolicyResult:
        result = await super().check(auth_ctx, requested_tools)
        return PolicyResult(result.allowed_tools, result.allowed_skills, rate_limit=self._rate_limit)


@pytest.fixture
async def make_session(faux_model, plugin_runner, tool_registry, skill_registry, jsonl_repo):
    await jsonl_repo.create(session_id="limited")

    def _make(rate_limit: int) -> AgentSession:
        pipeline = SecurityPipeline(
            validator=DefaultInputValidator(),
            authenticator=ApiKeyAuthenticator({k: frozenset({"user"}) for k in KEYS}, KEYS),
            policy=LimitedPolicy(rate_limit),
            sandbox=PermissiveSandbox(),
        )
        return AgentSession(
            model=faux_model,
            session_id="limited",
            security_pipeline=pipeline,
            plugin_runner=plugin_runner,
            tool_registry=tool_registry,
            skill_registry=skill_registry,
            session_repo=jsonl_repo,
        )

    return _make


async def _prompt(session: AgentSession, key: str) -> None:
    await session.prompt("안녕", credentials={"api_key": key})


async def test_requests_within_limit_pass_and_next_one_is_denied_with_user_id(make_session):
    session = make_session(rate_limit=3)
    for _ in range(3):
        await _prompt(session, "key-alice")

    with pytest.raises(PolicyDenied, match="Rate limit exceeded.*alice"):
        await _prompt(session, "key-alice")


async def test_users_have_separate_counters(make_session):
    session = make_session(rate_limit=1)
    await _prompt(session, "key-alice")

    await _prompt(session, "key-bob")

    with pytest.raises(PolicyDenied):
        await _prompt(session, "key-alice")


async def test_requests_older_than_window_expire(make_session, monkeypatch):
    offset = 0.0
    monkeypatch.setattr(
        session_module, "time", SimpleNamespace(monotonic=lambda: time.monotonic() + offset, time=time.time)
    )
    session = make_session(rate_limit=2)
    await _prompt(session, "key-alice")
    await _prompt(session, "key-alice")

    offset = 61.0

    await _prompt(session, "key-alice")
