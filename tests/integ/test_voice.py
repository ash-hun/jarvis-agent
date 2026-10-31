"""voice 기능: 읽기 문구 wav, PCM 웨이크워드, 음성 서비스 없는 TTS 폴백, 같은 답 읽기 알림 한 번을 검증한다."""

import json
import pytest

pytest.importorskip("fastapi")

from tests.fixtures.web_hud_helpers import web_assembly, web_client  # noqa: E402
from jarvis.voice.wake import FRAME_BYTES, WakeDetector  # noqa: E402
import jarvis.voice.voice_service as voice_service  # noqa: E402
from jarvis.ui.web.web_state import WebState  # noqa: E402

LOUD = b"\x01" * FRAME_BYTES
QUIET = b"\x00" * FRAME_BYTES


def loudness(frame: bytes) -> float:
    """가짜 웨이크워드 모델: 0 이 아닌 프레임이면 1.0."""
    return 1.0 if any(frame) else 0.0


@pytest.fixture
def make_client(monkeypatch, tmp_path):
    phrases = tmp_path / "phrases"
    phrases.mkdir()
    (phrases / "wake_up.wav").write_bytes(b"RIFF-wake")
    (phrases / "phrases.json").write_text(json.dumps({"wake_up": {"audio": "phrases/wake_up.wav"}}), "utf-8")

    def build(*, phrases_dir: str = str(phrases), wake: bool = False):
        if wake:
            monkeypatch.setattr(
                WebState, "_build_wake_factory", lambda self: lambda: WakeDetector(loudness, threshold=0.5)
            )
        env = {"VOICE__WAKE_MODEL_DIR": "", "VOICE__PHRASES_DIR": phrases_dir}
        return web_client(web_assembly(monkeypatch, tmp_path, **env))

    return build


@pytest.mark.parametrize(
    ("kwargs", "phrases", "wake"),
    [({"wake": True}, ["wake_up"], True), ({"phrases_dir": ""}, [], False)],
)
def test_connected_lists_phrases_and_wake_flag(make_client, kwargs, phrases, wake):
    with make_client(**kwargs) as client, client.websocket_connect("/ws?session_id=v1") as ws:
        voice = ws.receive_json()["voice"]

    assert voice["phrases"] == phrases
    assert voice["wake"] is wake


def test_phrase_wav_is_served_and_unknown_is_404(make_client):
    with make_client() as client:
        ok = client.get("/api/voice/phrases/wake_up")
        missing = client.get("/api/voice/phrases/hello")

    assert ok.status_code == 200
    assert ok.headers["content-type"] == "audio/wav"
    assert ok.content == b"RIFF-wake"
    assert missing.status_code == 404


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


def test_tts_request_without_voice_service_falls_back_to_browser(monkeypatch, tmp_path):
    """음성 서비스가 없어도 응답을 돌려줘야 HUD 가 '음성 처리 중'에 멈추지 않는다."""

    def no_voice(*_args, **_kwargs):
        raise RuntimeError("voice unavailable")

    monkeypatch.setattr(voice_service.VoiceService, "from_config", staticmethod(no_voice))

    with web_client(web_assembly(monkeypatch, tmp_path)) as c, c.websocket_connect("/ws?session_id=default") as ws:
        ws.receive_json()
        ws.send_json({"type": "voice_tts_request", "text": "물 마시기"})
        reply = ws.receive_json()
        # 기호는 지우고, 요청 id 는 그대로 돌려줘 화면이 멈춘 읽기의 결과를 가려낸다
        ws.send_json({"type": "voice_tts_request", "text": "- **물** 마시기", "id": 3})
        marked = ws.receive_json()

    assert reply == {"type": "voice_tts_audio", "data": "", "text": "물 마시기", "id": None}
    assert marked == {"type": "voice_tts_audio", "data": "", "text": "물 마시기", "id": 3}


def test_two_screens_reading_the_same_reply_notify_once(monkeypatch, tmp_path):
    sent: list[dict] = []

    async def notify(payload):
        sent.append(payload)

    assembly = web_assembly(monkeypatch, tmp_path, VOICE__WAKE_MODEL_DIR="")
    assembly.ctx.notifier = notify
    client = web_client(assembly)

    # 같은 세션을 연 두 화면이 같은 답을 읽고 각자 알려 온다
    with client, client.websocket_connect("/ws?session_id=v5") as a, client.websocket_connect("/ws?session_id=v5") as b:
        a.receive_json()
        b.receive_json()
        for ws in (a, b):
            ws.send_json({"type": "voice_tts_request", "text": "공고 세 건 찾았어요", "source": "reply"})
            ws.receive_json()

    assert [p["text"] for p in sent] == ["공고 세 건 찾았어요"]
