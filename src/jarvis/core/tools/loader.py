from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from jarvis.core.tools.registry import JarvisTool, ToolRegistry

if TYPE_CHECKING:
    pass


class ToolLoader:
    """
    파일 기반 툴 로더.
    - .py 파일: JarvisTool 클래스 또는 execute() 함수 포함
    - .yaml 파일: 선언적 메타데이터 + 동일 이름 .py 핸들러
    watchfiles로 핫리로드 지원.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._watch_task: asyncio.Task | None = None

    async def load_directory(self, path: str) -> list[str]:
        loaded = []
        dir_path = Path(path).expanduser()
        if not dir_path.exists():
            return loaded

        for yaml_file in dir_path.glob("*.yaml"):
            try:
                tool = await self._load_yaml_tool(yaml_file)
                if tool:
                    self._registry.register_force(tool)
                    loaded.append(tool.name)
            except Exception as exc:
                print(f"[ToolLoader] Failed to load {yaml_file.name}: {exc}")

        for py_file in dir_path.glob("*.py"):
            if py_file.stem + ".yaml" in [f.name for f in dir_path.glob("*.yaml")]:
                continue
            try:
                tool = await self._load_python_tool(py_file)
                if tool:
                    self._registry.register_force(tool)
                    loaded.append(tool.name)
            except Exception as exc:
                print(f"[ToolLoader] Failed to load {py_file.name}: {exc}")

        return loaded

    async def watch(self, path: str) -> None:
        try:
            from watchfiles import awatch
        except ImportError:
            return

        async for changes in awatch(path):
            await self.load_directory(path)

    async def _load_yaml_tool(self, yaml_file: Path) -> JarvisTool | None:
        with open(yaml_file) as f:
            meta = yaml.safe_load(f)

        py_file = yaml_file.with_suffix(".py")
        if not py_file.exists():
            return None

        module = _load_module(py_file)
        execute_fn = getattr(module, "execute", None)
        if execute_fn is None:
            return None

        return _FunctionTool(
            name=meta["name"],
            description=meta.get("description", ""),
            parameters=meta.get("parameters", {}),
            execution_mode=meta.get("execution_mode", "parallel"),
            execute_fn=execute_fn,
        )

    async def _load_python_tool(self, py_file: Path) -> JarvisTool | None:
        module = _load_module(py_file)

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and attr_name != "object" and hasattr(attr, "name"):
                try:
                    instance = attr()
                    if isinstance(instance, JarvisTool):
                        return instance
                except Exception:
                    pass

        execute_fn = getattr(module, "execute", None)
        name = getattr(module, "TOOL_NAME", py_file.stem.replace("_", "-"))
        description = getattr(module, "TOOL_DESCRIPTION", "")
        parameters = getattr(module, "TOOL_PARAMETERS", {"type": "object", "properties": {}})

        if execute_fn:
            return _FunctionTool(
                name=name,
                description=description,
                parameters=parameters,
                execution_mode="parallel",
                execute_fn=execute_fn,
            )
        return None


def _load_module(py_file: Path):
    spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[py_file.stem] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class _FunctionTool:
    def __init__(self, name: str, description: str, parameters: dict, execution_mode: str, execute_fn) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.execution_mode = execution_mode
        self._fn = execute_fn

    async def execute(self, tool_call_id: str, params: dict, signal=None):
        from jarvis.model_layer.types import TextContent, ToolResultMessage
        try:
            result = await self._fn(tool_call_id=tool_call_id, params=params)
            if isinstance(result, dict):
                content = result.get("content", str(result))
            else:
                content = str(result)
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=content)],
            )
        except Exception as exc:
            from jarvis.model_layer.types import TextContent, ToolResultMessage
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=str(exc))],
                is_error=True,
            )
