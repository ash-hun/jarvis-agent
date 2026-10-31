"""[core] 디렉터리의 .py 파일에서 플러그인 클래스를 찾아 PluginRunner 에 등록한다."""

import sys
import importlib.util
from pathlib import Path

from jarvis.core.plugins.plugins_protocol import JarvisPlugin
from jarvis.core.plugins.runner import PluginRunner
from jarvis.common.logger import get_logger

logger = get_logger(__name__)


class PluginLoader:
    """디렉터리에서 JarvisPlugin 모양의 구현체를 자동 로드. 각 .py 파일에서 name, version 을 가진 클래스를 등록."""

    def __init__(self, runner: PluginRunner) -> None:
        self._runner = runner

    async def load_directory(self, path: str) -> list[str]:
        loaded: list[str] = []
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
                logger.info(f"[PluginLoader] Failed to load {py_file.name}: {exc}")

        return loaded


def _load_plugin(py_file: Path) -> JarvisPlugin | None:
    """상속은 묻지 않는다. name 과 version 을 가진 첫 클래스의 인스턴스(덕 타이핑 플러그인 포함)."""
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
                return attr()  # type: ignore[no-any-return]  # 상속하지 않은 덕 타이핑 플러그인도 받는다
            except Exception:
                pass
    return None
