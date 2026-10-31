"""Web HUD 음성: 읽기 문구 wav 를 내주고, 바이너리 프레임의 PCM 으로 웨이크워드를 감지해 voice_wake 를 보낸다."""

import json
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from jarvis.voice.wake import FRAME_BYTES, WakeDetector  # noqa: E402
from jarvis.jarvis_config import JarvisSettings  # noqa: E402
from jarvis.app.infra_builder import build_app  # noqa: E402
from jarvis.ui.web.web_state import WebState  # noqa: E402
from jarvis.ui.web.server import create_app  # noqa: E402

LOUD = b"\x01" * FRAME_BYTES
QUIET = b"\x00" * FRAME_BYTES


def loudness(frame: bytes) -> float:
    """가짜 웨이크워드 모델: 0 이 아닌 프레임이면 1.0."""
    return 1.0 if any(frame) else 0.0


@pytest.fixture
def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PROACTIVE__DAEMON_ENABLED", "false")
    monkeypatch.setenv("JARVIS_SCHEDULER__ENABLED", "false")
    monkeypatch.setenv("JARVIS_MEMORY__BACKEND", "in_memory")
    monkeypatch.setenv("JARVIS_SESSION__PERSISTENCE_BACKEND", "jsonl")
    monkeypatch.setenv("JARVIS_SESSION__SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("JARVIS_VOICE__WAKE_MODEL_DIR", "")
    phrases = tmp_path / "phrases"
    phrases.mkdir()
    (phrases / "wake_up.wav").write_bytes(b"RIFF-wake")
    (phrases / "phrases.json").write_text(json.dumps({"wake_up": {"audio": "phrases/wake_up.wav"}}), "utf-8")

    def build(*, phrases_dir: str = str(phrases), wake: bool = False) -> TestClient:
        monkeypatch.setenv("JARVIS_VOICE__PHRASES_DIR", phrases_dir)
        if wake:
            monkeypatch.setattr(
                WebState, "_build_wake_factory", lambda self: lambda: WakeDetector(loudness, threshold=0.5)
            )
        return TestClient(create_app(build_app(JarvisSettings()), initial_session_id="default"))

    return build


def test_connected_lists_phrases_and_wake_flag(make_client):
    with make_client(wake=True) as client, client.websocket_connect("/ws?session_id=v1") as ws:
        voice = ws.receive_json()["voice"]

    assert voice["phrases"] == ["wake_up"]
    assert voice["wake"] is True


def test_phrase_wav_is_served_and_unknown_is_404(make_client):
    with make_client() as client:
        ok = client.get("/api/voice/phrases/wake_up")
        missing = client.get("/api/voice/phrases/hello")

    assert ok.status_code == 200
    assert ok.headers["content-type"] == "audio/wav"
    assert ok.content == b"RIFF-wake"
    assert missing.status_code == 404


def test_without_phrases_dir_nothing_is_listed(make_client):
    with make_client(phrases_dir="") as client, client.websocket_connect("/ws?session_id=v2") as ws:
        voice = ws.receive_json()["voice"]

    assert voice["phrases"] == []
    assert voice["wake"] is False


def test_binary_pcm_wakes_once_then_json_still_works(make_client):
    with make_client(wake=True) as client, client.websocket_connect("/ws?session_id=v3") as ws:
        ws.receive_json()
        ws.send_bytes(QUIET)
        # 반 프레임씩 보내도 이어 붙여 한 프레임으로 본다
        ws.send_bytes(LOUD[: FRAME_BYTES // 2])
        ws.send_bytes(LOUD[FRAME_BYTES // 2 :])
        woke = ws.receive_json()
        # 이름 끝의 높은 프레임은 무시한다. 다음으로 오는 것은 JSON 메시지의 응답이다
        ws.send_bytes(LOUD * 3)
        ws.send_json({"type": "voice_tts_request", "text": "", "id": 7})
        after = ws.receive_json()

    assert woke == {"type": "voice_wake", "score": 1.0}
    assert after["type"] == "voice_tts_audio"
    assert after["id"] == 7


def test_binary_frames_are_ignored_when_wake_is_off(make_client):
    with make_client() as client, client.websocket_connect("/ws?session_id=v4") as ws:
        ws.receive_json()
        ws.send_bytes(LOUD)
        ws.send_json({"type": "voice_tts_request", "text": "", "id": 1})
        reply = ws.receive_json()

    assert reply["type"] == "voice_tts_audio"


def test_two_screens_reading_the_same_reply_notify_once(make_client):
    sent: list[dict] = []

    async def notify(payload):
        sent.append(payload)

    assembly = build_app(JarvisSettings())
    assembly.ctx.notifier = notify
    client = TestClient(create_app(assembly, initial_session_id="default"))
    # 같은 세션을 연 두 화면이 같은 답을 읽고 각자 알려 온다
    with client, client.websocket_connect("/ws?session_id=v5") as a, client.websocket_connect("/ws?session_id=v5") as b:
        a.receive_json()
        b.receive_json()
        for ws in (a, b):
            ws.send_json({"type": "voice_tts_request", "text": "공고 세 건 찾았어요", "source": "reply"})
            ws.receive_json()

    assert [p["text"] for p in sent] == ["공고 세 건 찾았어요"]
