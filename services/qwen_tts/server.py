"""[services] Mac GPU(MLX)에서 Qwen3-TTS 로 JARVIS 목소리를 합성해 WAV 로 돌려주는 로컬 HTTP 서버."""

import io
import os
import json
import struct
import soundfile
import threading
import numpy as np
import mlx.core as mx
from mlx_audio.tts.utils import load_model
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("QWEN_TTS_HOST", "127.0.0.1")
PORT = int(os.environ.get("QWEN_TTS_PORT", "8770"))
# llmclick 이 만든 목소리: voice.json(모델, 버전, 기준 녹음 대본)과 reference.wav. 기준 녹음은 손대지 않는다
VOICE_DIR = os.path.expanduser(os.environ.get("QWEN_VOICE_DIR", "~/.jarvis/voices/qwen"))
# 매 요청 같은 seed 라 같은 문장은 같은 소리다(다시 불러도 결과가 같다)
SEED = int(os.environ.get("QWEN_TTS_SEED", "7"))
# 영어 옮기기가 45단어로 줄인다. 그보다 길면 잘못 온 요청이다
MAX_CHARS = 600
WARMUP_TEXT = "At your service, sir."
# 조각 하나의 소리 길이(초). 데운 뒤 첫 조각이 0.22초에 나온다(2026-10-27 측정)
STREAM_INTERVAL_SEC = 0.32

with open(os.path.join(VOICE_DIR, "voice.json")) as f:
    voice = json.load(f)
reference = os.path.join(VOICE_DIR, "reference.wav")
model = load_model(voice["model"], revision=voice["revision"])
# MLX 모델은 동시에 두 번 생성하지 못한다. 요청은 한 번에 하나씩
lock = threading.Lock()


def synthesize(text: str) -> bytes:
    with lock:
        mx.random.seed(SEED)
        results = model.generate(text=text, ref_audio=reference, ref_text=voice["reference_text"])
        samples = np.concatenate([np.array(r.audio) for r in results])
    buf = io.BytesIO()
    soundfile.write(buf, samples, model.sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def pcm16(audio: object) -> bytes:
    return (np.clip(np.array(audio), -1.0, 1.0) * 32767).astype("<i2").tobytes()


def synthesize_stream(text: str):
    """소리를 조각마다 PCM s16le 로 낸다. 받는 쪽이 끊으면 생성도 멈추고 잠금이 풀린다."""
    with lock:
        mx.random.seed(SEED)
        results = model.generate(
            text=text,
            ref_audio=reference,
            ref_text=voice["reference_text"],
            stream=True,
            streaming_interval=STREAM_INTERVAL_SEC,
        )
        for r in results:
            yield pcm16(r.audio)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        self._reply(200, "application/json", json.dumps({"model": voice["model"], "ready": True}).encode())

    def do_POST(self) -> None:
        if self.path not in ("/tts", "/tts/stream"):
            self.send_error(404)
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            text = str(body.get("text", "")).strip()
        except (ValueError, TypeError):
            self.send_error(400, 'body must be JSON {"text": ...}')
            return
        if not text or len(text) > MAX_CHARS:
            self.send_error(400, f"text must be 1~{MAX_CHARS} chars")
            return
        if self.path == "/tts/stream":
            self._stream(text)
            return
        try:
            wav = synthesize(text)
        except Exception as exc:
            self.send_error(500, repr(exc)[:200])
            return
        self._reply(200, "audio/wav", wav)

    def _stream(self, text: str) -> None:
        """조각마다 4바이트 길이(LE)와 PCM s16le 를 보내고, 길이 0 으로 끝을 알린다. 그것 없이 닫히면 중간에 실패한 것이다."""
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("X-Sample-Rate", str(model.sample_rate))
        self.end_headers()
        try:
            for chunk in synthesize_stream(text):
                self.wfile.write(struct.pack("<I", len(chunk)) + chunk)
                self.wfile.flush()
            self.wfile.write(struct.pack("<I", 0))
        except (BrokenPipeError, ConnectionResetError):
            pass  # 받는 쪽이 읽기를 멈췄다
        except Exception as exc:
            # 머리를 이미 보냈다. 끝 표시 없이 닫아 받는 쪽이 중간에 끊긴 것으로 안다
            print(f"[qwen-tts] stream failed: {exc!r}", flush=True)

    def _reply(self, status: int, content_type: str, data: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[qwen-tts] {self.address_string()} {format % args}", flush=True)


if __name__ == "__main__":
    # 첫 요청이 컴파일과 캐시를 기다리지 않게. 조각 생성은 다른 길이라 따로 데운다
    synthesize(WARMUP_TEXT)
    for _ in synthesize_stream(WARMUP_TEXT):
        pass
    print(f"[qwen-tts] ready on {HOST}:{PORT} ({voice['model']})", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
