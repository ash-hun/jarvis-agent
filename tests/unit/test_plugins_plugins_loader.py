"""plugins 의 PluginLoader: 디렉터리의 덕 타이핑과 상속 플러그인을 등록하고 깨진 파일은 기록하고 넘어가는지 검증한다."""

from jarvis.core.plugins.plugins_loader import PluginLoader
from jarvis.core.plugins.runner import PluginRunner


async def test_missing_directory_loads_nothing(tmp_path):
    assert await PluginLoader(PluginRunner()).load_directory(str(tmp_path / "nope")) == []


async def test_loads_duck_typed_and_subclass_plugins(tmp_path):
    (tmp_path / "duck.py").write_text("class Duck:\n    name = 'duck'\n    version = '0.1'\n")
    (tmp_path / "sub.py").write_text(
        "from jarvis.core.plugins.plugins_protocol import JarvisPlugin\n\n"
        "class Sub(JarvisPlugin):\n    name = 'sub'\n    version = '0.1'\n"
    )

    loaded = await PluginLoader(PluginRunner()).load_directory(str(tmp_path))

    assert sorted(loaded) == ["duck", "sub"]


async def test_broken_file_is_logged(tmp_path, capsys):
    (tmp_path / "bad.py").write_text("raise RuntimeError('nope')\n")

    loaded = await PluginLoader(PluginRunner()).load_directory(str(tmp_path))

    assert loaded == []
    assert "[PluginLoader] Failed to load bad.py: nope" in capsys.readouterr().out
