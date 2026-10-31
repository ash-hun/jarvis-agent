"""[core] 사용자가 디스코드 음성 채널에 있으면 봇이 그 채널에서 알림을 읽고, 없으면 글 채널로 넘긴다."""

import os
import asyncio
import tempfile
from typing import Any
from collections.abc import Awaitable, Callable

from jarvis.core.notify.webhook import headline
from jarvis.common.logger import get_logger

# 이보다 길면 앞부분만 읽고 전문은 글로도 남긴다. 공고 목록처럼 긴 알림을 몇 분씩 읽지 않게
SPEAK_MAX_CHARS = 300
CUT_NOTE = "나머지는 디스코드 글로 남겼어요."
READY_TIMEOUT_SEC = 30.0
CONNECT_TIMEOUT_SEC = 15.0
PLAY_TIMEOUT_SEC = 180.0
# 제목 앞 그림 글자. 읽지 않는다
HEAD_MARKS = "⏰⏱💬💭🔊 "

Notify = Callable[[dict[str, Any]], Awaitable[None]]

logger = get_logger(__name__)


class VoiceGateway:
    """디스코드에 닿는 부분. 테스트는 가짜를 넣는다. 기본은 사용자가 음성 채널에 없는 것으로 본다(글로만 보낸다)."""

    async def channel_of(self, user_id: int) -> Any | None:
        return None

    async def play(self, channel: Any, wav: bytes) -> None:
        return None


def speech_of(payload: dict[str, Any], clean: Callable[[str], str]) -> tuple[str, bool]:
    """읽을 문장과 잘렸는지. 누가 보낸 알림인지 이름부터 읽는다. 순수 함수."""
    head, body = headline(payload)
    who = str(payload.get("agent_name") or "")
    title = head.lstrip(HEAD_MARKS).strip()
    parts = [p for p in (who, "" if title == who else title, clean(body)) if p]
    if not parts:
        return "", False
    # 이름 끝의 마침표(K.A.R.E.N.)와 잇는 마침표가 겹치지 않게
    lead = ". ".join(p.rstrip(". ") for p in parts[:-1])
    text = f"{lead}. {parts[-1]}" if lead else parts[-1]
    if len(text) <= SPEAK_MAX_CHARS:
        return text, False
    return text[:SPEAK_MAX_CHARS].rsplit(" ", 1)[0] + ". " + CUT_NOTE, True


class DiscordVoice:
    """user_id 가 있는 음성 채널을 찾아 읽는다. 한 번에 하나씩 읽는다(겹쳐 들어오면 차례를 기다린다)."""

    def __init__(
        self,
        gateway: VoiceGateway,
        user_id: int,
        synthesize: Callable[[str], Awaitable[bytes]],
        clean: Callable[[str], str],
    ) -> None:
        self._gateway = gateway
        self._user_id = user_id
        self._synthesize = synthesize
        self._clean = clean
        self._lock = asyncio.Lock()

    async def speak(self, payload: dict[str, Any]) -> tuple[bool, bool]:
        """(읽었는가, 잘라 읽었는가). 사용자가 음성 채널에 없거나 어디서든 실패하면 (False, False)."""
        text, cut = speech_of(payload, self._clean)
        if not text:
            return False, False
        async with self._lock:
            try:
                channel = await self._gateway.channel_of(self._user_id)
                if channel is None:
                    return False, False
                wav = await self._synthesize(text)
                if not wav:
                    return False, False
                await self._gateway.play(channel, wav)
            except Exception as exc:
                logger.info(f"[Notify] discord voice failed, falling back to text: {exc!r}")
                return False, False
        return True, cut


def voice_first(voice: DiscordVoice, types: set[str], text: Notify) -> Notify:
    """types 의 알림은 먼저 음성으로 읽는다. 못 읽었거나 잘라 읽었으면 글로도 보낸다."""

    async def notify(payload: dict[str, Any]) -> None:
        if payload.get("type") in types:
            spoken, cut = await voice.speak(payload)
            if spoken and not cut:
                return
        await text(payload)

    return notify


class DiscordGateway(VoiceGateway):
    """discord.py 봇 하나. 처음 알림 때 접속하고 프로세스가 끝날 때까지 둔다. 읽을 때만 채널에 들어갔다 나온다."""

    def __init__(self, token: str, guild_id: int) -> None:
        self._token = token
        self._guild_id = guild_id
        self._client: Any = None
        self._task: asyncio.Task[None] | None = None

    async def _ready(self) -> Any:
        if self._task is not None and self._task.done():
            # 로그인이 끊겼거나 토큰이 틀렸다. 다음 알림에서 다시 붙는다
            error = self._task.exception() if not self._task.cancelled() else None
            self._client, self._task = None, None
            raise RuntimeError(f"discord bot stopped: {error!r}")
        if self._client is None:
            import discord

            intents = discord.Intents.none()
            intents.guilds = True
            intents.voice_states = True
            self._client = discord.Client(intents=intents)
            self._task = asyncio.create_task(self._client.start(self._token))
        await asyncio.wait_for(self._client.wait_until_ready(), READY_TIMEOUT_SEC)
        return self._client

    async def channel_of(self, user_id: int) -> Any | None:
        client = await self._ready()
        guild = client.get_guild(self._guild_id)
        if guild is None:
            raise RuntimeError(f"bot is not in guild {self._guild_id}")
        for channel in [*guild.voice_channels, *guild.stage_channels]:
            if user_id in channel.voice_states:
                return channel
        return None

    async def play(self, channel: Any, wav: bytes) -> None:
        import discord

        if channel.guild.voice_client is not None:
            # 지난번 재생이 비정상으로 끝나 붙어 있던 연결. 남겨 두면 connect 가 거절된다
            await channel.guild.voice_client.disconnect(force=True)
        fd, path = tempfile.mkstemp(suffix=".wav")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(wav)
            client = await channel.connect(timeout=CONNECT_TIMEOUT_SEC)
            try:
                loop = asyncio.get_running_loop()
                done = asyncio.Event()
                client.play(discord.FFmpegPCMAudio(path), after=lambda _err: loop.call_soon_threadsafe(done.set))
                await asyncio.wait_for(done.wait(), PLAY_TIMEOUT_SEC)
            finally:
                await client.disconnect(force=True)
        finally:
            os.unlink(path)
