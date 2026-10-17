"""[scripts] Piper 영어 음성의 합성 시간과 실시간 대비 배율(RTF)을 잰다. 백엔드 컨테이너 안에서 돈다."""

import asyncio
import io
import json
import sys
import time
import wave

from jarvis.config import get_settings
from jarvis.voice.providers.piper import PiperTTSProvider

SENTENCES = [
    "Good evening.",
    "I have prepared the agenda for next week's review meeting.",
    "The deployment finished, but the error rate rose slightly. Shall I pull the logs for you?",
    "Your report is due in ten minutes. I can summarize the remaining items and draft a short note to your manager.",
]


async def main() -> None:
    options = get_settings().voice.english_tts_options()
    tts = PiperTTSProvider(**options)  # type: ignore[arg-type]
    await tts.synthesize("Warm up.")
    rows = []
    for text in SENTENCES:
        start = time.perf_counter()
        audio = await tts.synthesize(text, "en")
        took = time.perf_counter() - start
        with wave.open(io.BytesIO(audio)) as w:
            seconds = w.getnframes() / w.getframerate()
        rows.append(
            {"chars": len(text), "synth_s": round(took, 3), "audio_s": round(seconds, 2), "rtf": round(took / seconds, 3)}
        )
    json.dump(rows, sys.stdout)


asyncio.run(main())
