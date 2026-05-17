from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from jarvis.core.plugins.runner import PluginRunner


class PluginLoader:
    """
    디렉터리에서 JarvisPlugin 구현체를 자동 로드.
    각 .py 파일에서 'name' 속성을 가진 클래스를 찾아 등록.
    """

    def __init__(self, runner: PluginRunner) -> None:
        self._runner = runner

    async def load_directory(self, path: str) -> list[str]:
        loaded = []
        dir_path = Path(path).expanduser()
        if not dir_path.exists():
            return loaded

        for py_file in dir_path.glob("*.py"):
            try:
                plugin = _load_plugin(py_file)
                if plugin:
                    self._runner.register(plugin)
                    loaded.append(plugin.name)
            except Exception as exc:
                print(f"[PluginLoader] Failed to load {py_file.name}: {exc}")

        return loaded


def _load_plugin(py_file: Path):
    spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[f"_jarvis_plugin_{py_file.stem}"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
            isinstance(attr, type)
            and attr_name not in ("object",)
            and hasattr(attr, "name")
            and hasattr(attr, "version")
        ):
            try:
                return attr()
            except Exception:
                pass
    return None
