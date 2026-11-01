"""[app] plugin.watch_files 가 켜져 있으면 도구, 스킬, 플러그인 디렉터리를 지켜보다 바뀐 디렉터리만 다시 읽는다."""

import asyncio
import contextlib
from pathlib import Path
from collections.abc import Awaitable, Callable, Iterable, Mapping

from jarvis.common.logger import get_logger

# 디렉터리 하나를 다시 읽는 함수. 실은 이름 목록을 돌려준다
Reload = Callable[[str], Awaitable[list[str]]]

logger = get_logger(__name__)


class ExtensionWatcher:
    """디렉터리별 다시 읽기 함수를 받아, 파일이 바뀌면 그 디렉터리의 함수만 부른다.

    다시 읽기는 이름이 같으면 덮어쓰는 등록이라 몇 번 불려도 같은 상태가 된다.
    """

    # ponytail: 지운 파일의 도구와 스킬은 재시작 전까지 남는다, 지운 확장을 바로 빼야 하면 레지스트리에 출처 경로를 둔다
    def __init__(self, reloaders: Mapping[str, Reload]) -> None:
        self._reloaders = {Path(d).expanduser().resolve(): fn for d, fn in reloaders.items()}
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def directories(self) -> list[str]:
        return sorted(str(d) for d in self._reloaders)

    async def start(self) -> None:
        """감시를 띄운다. 이미 돌고 있거나 지켜볼 디렉터리가 없으면 아무것도 안 한다."""
        if self._task is not None or not self._reloaders:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def reload(self, changed: Iterable[str]) -> list[str]:
        """바뀐 파일이 속한 디렉터리만 다시 읽고 실은 이름을 돌려준다. 한 디렉터리가 실패해도 다른 쪽은 읽는다."""
        paths = [Path(p).resolve() for p in changed]
        loaded: list[str] = []
        for directory, reload_dir in self._reloaders.items():
            if not any(p.is_relative_to(directory) for p in paths):
                continue
            try:
                names = await reload_dir(str(directory))
            except Exception as exc:
                logger.info(f"[ExtensionWatcher] reload failed: {directory}: {exc!r}")
                continue
            logger.info(f"[ExtensionWatcher] reloaded {directory}: {names}")
            loaded.extend(names)
        return loaded

    async def _run(self) -> None:
        try:
            from watchfiles import awatch
        except ImportError:
            logger.info("[ExtensionWatcher] watchfiles not installed, file watching is off")
            return
        dirs = [str(d) for d in self._reloaders]
        async for changes in awatch(*dirs, stop_event=self._stop):
            await self.reload(path for _change, path in changes)
