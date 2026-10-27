"""[services] Mac GPU(MLX)에서 Qwen3-TTS 로 JARVIS 목소리를 합성해 WAV 로 돌려주는 로컬 HTTP 서버."""

import io
import os
import json
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


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        self._reply(200, "application/json", json.dumps({"model": voice["model"], "ready": True}).encode())

    def do_POST(self) -> None:
        if self.path != "/tts":
            self.send_error(404)
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            text = str(body.get("text", "")).strip()
        except (ValueError, TypeError):
            self.send_error(400, "body must be JSON {\"text\": ...}")
            return
        if not text or len(text) > MAX_CHARS:
            self.send_error(400, f"text must be 1~{MAX_CHARS} chars")
            return
        try:
            wav = synthesize(text)
        except Exception as exc:
            self.send_error(500, repr(exc)[:200])
            return
        self._reply(200, "audio/wav", wav)

    def _reply(self, status: int, content_type: str, data: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[qwen-tts] {self.address_string()} {format % args}", flush=True)


if __name__ == "__main__":
    synthesize(WARMUP_TEXT)  # 첫 요청이 컴파일과 캐시를 기다리지 않게
    print(f"[qwen-tts] ready on {HOST}:{PORT} ({voice['model']})", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
