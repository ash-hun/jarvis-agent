"""[ui] TuiVoiceController: 서버 음성 프로바이더와 시스템 오디오 도구(afplay, sox 등)로 TUI 음성 입출력을 한다."""

# 터미널엔 Web Speech API 가 없어 서버 프로바이더를 쓴다. player/recorder 는 주입 가능(테스트는 fake)
from __future__ import annotations

import asyncio
import shutil
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.voice.service import VoiceService

Player = Callable[[bytes], Awaitable[None]]
Recorder = Callable[[float], Awaitable[bytes]]


class VoiceUnavailable(Exception):
    """음성 입출력에 필요한 시스템 도구/프로바이더가 없을 때."""


# 플랫폼별 WAV 재생 명령 — 먼저 발견되는 것을 사용
_PLAYERS: list[tuple[str, Callable[[str], list[str]]]] = [
    ("afplay", lambda f: ["afplay", f]),                                   # macOS
    ("paplay", lambda f: ["paplay", f]),                                   # PulseAudio
    ("aplay", lambda f: ["aplay", "-q", f]),                               # ALSA
    ("ffplay", lambda f: ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", f]),
]

# 플랫폼별 N초 녹음 명령 (WAV 출력)
_RECORDERS: list[tuple[str, Callable[[str, float], list[str]]]] = [
    ("sox", lambda f, s: ["sox", "-d", "-t", "wav", f, "trim", "0", str(s)]),       # cross-platform
    ("arecord", lambda f, s: ["arecord", "-q", "-d", str(int(s)), "-f", "cd", "-t", "wav", f]),
]


def _detect(table: list[tuple[str, Callable[..., list[str]]]]) -> Callable[..., list[str]] | None:
    for name, build in table:
        if shutil.which(name):
            return build
    return None


async def play_wav_via_system(audio: bytes) -> None:
    """WAV bytes를 임시 파일에 쓰고 시스템 플레이어로 재생한다."""
    build = _detect(_PLAYERS)
    if build is None:
        raise VoiceUnavailable("재생 도구를 찾을 수 없습니다 (afplay/paplay/aplay/ffplay 중 하나 필요)")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio)
        path = tmp.name
    try:
        proc = await asyncio.create_subprocess_exec(
            *build(path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    finally:
        Path(path).unlink(missing_ok=True)


async def record_wav_via_system(seconds: float) -> bytes:
    """시스템 레코더로 seconds초간 녹음해 WAV bytes를 반환한다."""
    build = _detect(_RECORDERS)
    if build is None:
        raise VoiceUnavailable("녹음 도구를 찾을 수 없습니다 (sox 또는 arecord 필요)")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        path = tmp.name
    try:
        proc = await asyncio.create_subprocess_exec(
            *build(path, seconds),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return Path(path).read_bytes()
    finally:
        Path(path).unlink(missing_ok=True)


class TuiVoiceController:
    """TUI 음성 입출력 — VoiceService + 시스템 오디오 백엔드를 연결한다."""

    def __init__(
        self,
        voice_service: VoiceService,
        *,
        player: Player | None = None,
        recorder: Recorder | None = None,
    ) -> None:
        self._svc = voice_service
        self._player = player or play_wav_via_system
        self._recorder = recorder or record_wav_via_system

    @property
    def can_speak(self) -> bool:
        """browser TTS 프로바이더는 터미널에서 재생할 오디오를 만들지 않는다."""
        return not self._svc.tts_is_browser

    @property
    def can_listen(self) -> bool:
        """browser STT 프로바이더는 서버 전사를 하지 않는다."""
        return not self._svc.stt_is_browser

    async def speak(self, text: str, lang: str = "ko") -> bool:
        """text를 합성해 재생한다. 합성 결과가 없으면(browser 프로바이더) False."""
        if not text.strip():
            return False
        audio = await self._svc.synthesize(text, lang)
        if not audio:
            return False
        await self._player(audio)
        return True

    async def listen(self, seconds: float = 5.0) -> str:
        """seconds초 녹음 후 전사한 텍스트를 반환한다."""
        audio = await self._recorder(seconds)
        if not audio:
            return ""
        text: str = await self._svc.transcribe(audio)
        return text
