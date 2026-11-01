"""plugins 의 ExtensionWatcher: 바뀐 디렉터리만 다시 읽고, 한 디렉터리의 실패가 다른 쪽을 막지 않는지 검증한다."""

from jarvis.app.extension_watcher import ExtensionWatcher


def _recorder(calls: list[str], names: list[str]):
    async def reload(directory: str) -> list[str]:
        calls.append(directory)
        return names

    return reload


async def test_reload_reads_only_the_directory_that_changed(tmp_path):
    tools, skills = tmp_path / "tools", tmp_path / "skills"
    tools.mkdir()
    skills.mkdir()
    calls: list[str] = []
    watcher = ExtensionWatcher({str(tools): _recorder(calls, ["t"]), str(skills): _recorder(calls, ["s"])})

    loaded = await watcher.reload([str(tools / "new.py")])

    assert loaded == ["t"]
    assert calls == [str(tools.resolve())]


async def test_failed_reload_does_not_block_other_directory(tmp_path):
    bad, good = tmp_path / "bad", tmp_path / "good"
    bad.mkdir()
    good.mkdir()

    async def boom(_directory: str) -> list[str]:
        raise RuntimeError("broken")

    calls: list[str] = []
    watcher = ExtensionWatcher({str(bad): boom, str(good): _recorder(calls, ["g"])})

    assert await watcher.reload([str(bad / "a.py"), str(good / "b.md")]) == ["g"]


async def test_start_without_directories_does_nothing():
    watcher = ExtensionWatcher({})

    await watcher.start()
    await watcher.stop()

    assert watcher.directories == []
