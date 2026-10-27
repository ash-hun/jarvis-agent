"""[services] Qwen3-TTS 합성 속도(로드, 문장별 합성 시간, 소리 길이, RTF): bench.py <voice 디렉터리> <출력>."""

import sys
import json
import time
import platform
import soundfile
import numpy as np
import mlx.core as mx
from mlx_audio.tts.utils import load_model

VOICE_DIR, OUT_DIR = sys.argv[1], sys.argv[2]
SENTENCES = [
    "Yes, sir?",
    "Sir, I've put it on your screen.",
    "I'm sorry, sir. I didn't catch that.",
    "Sir, your meeting with the team starts in ten minutes.",
    "Sir, the deployment finished without errors, and I've sent the summary to your inbox as requested.",
]

with open(f"{VOICE_DIR}/voice.json") as f:
    voice = json.load(f)
t0 = time.time()
model = load_model(voice["model"], revision=voice["revision"])
load_sec = time.time() - t0
print(json.dumps({"where": platform.system(), "device": str(mx.default_device()), "load_sec": round(load_sec, 1)}))


def speak(text, seed=7):
    mx.random.seed(seed)
    start = time.time()
    results = model.generate(text=text, ref_audio=f"{VOICE_DIR}/reference.wav", ref_text=voice["reference_text"])
    samples = np.concatenate([np.array(r.audio) for r in results])
    return time.time() - start, samples


speak("Warming up, sir.")  # 첫 호출의 컴파일과 캐시를 빼고 잰다
for i, text in enumerate(SENTENCES):
    sec, samples = speak(text)
    audio = len(samples) / model.sample_rate
    soundfile.write(f"{OUT_DIR}/{i}.wav", samples, model.sample_rate, subtype="PCM_16")
    print(json.dumps({"i": i, "words": len(text.split()), "synth_sec": round(sec, 2), "audio_sec": round(audio, 2),
                      "rtf": round(sec / audio, 2)}), flush=True)
