"""[core] 디렉터리의 .py / .yaml 파일에서 도구를 읽어 ToolRegistry 에 등록하고 바뀌면 다시 읽는다."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from jarvis.common.logger import get_logger
from jarvis.core.tools.registry import JarvisTool, ToolRegistry
from jarvis.model_layer.types import TextContent, ToolResultMessage

# 사용자 도구는 JarvisTool 을 상속하지 않아도 된다. 예전 runtime_checkable Protocol 검사와 같은 멤버로 모양만 본다
TOOL_MODULE_PREFIX = "_jarvis_tool_"
TOOL_MEMBERS = ("name", "description", "parameters", "execution_mode", "execute")
TOOL_METHODS = frozenset({"execute"})
DEFAULT_EXECUTION_MODE = "parallel"

# 사용자 모듈의 execute(tool_call_id=..., params=...) 함수. 반환은 dict(content 키) 또는 아무 값
ToolFunction = Callable[..., Awaitable[Any]]

logger = get_logger(__name__)


def default_parameters() -> dict[str, Any]:
    """TOOL_PARAMETERS 가 없는 모듈의 스키마. 도구끼리 같은 dict 를 나눠 쓰지 않도록 매번 새로 만든다."""
    return {"type": "object", "properties": {}}


def looks_like_tool(obj: object) -> bool:
    """JarvisTool 과 같은 모양인가. 상속 여부는 묻지 않는다.

    예전 runtime_checkable 검사(3.12)와 같게 getattr_static 으로 찾고, 메서드 자리가 None 이면 아니다.
    """
    for member in TOOL_MEMBERS:
        try:
            value = inspect.getattr_static(obj, member)
        except AttributeError:
            return False
        if member in TOOL_METHODS and value is None:
            return False
    return True


class ToolLoader:
    """파일 기반 툴 로더. watchfiles 로 핫리로드 지원.

    - .py 파일: JarvisTool 모양의 클래스 또는 execute() 함수 포함
    - .yaml 파일: 선언적 메타데이터 + 동일 이름 .py 핸들러
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._watch_task: asyncio.Task[None] | None = None

    async def load_directory(self, path: str) -> list[str]:
        loaded: list[str] = []
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
                logger.info(f"[ToolLoader] Failed to load {yaml_file.name}: {exc}")

        for py_file in dir_path.glob("*.py"):
            if py_file.stem + ".yaml" in [f.name for f in dir_path.glob("*.yaml")]:
                continue
            try:
                tool = await self._load_python_tool(py_file)
                if tool:
                    self._registry.register_force(tool)
                    loaded.append(tool.name)
            except Exception as exc:
                logger.info(f"[ToolLoader] Failed to load {py_file.name}: {exc}")

        return loaded

    async def watch(self, path: str) -> None:
        try:
            from watchfiles import awatch
        except ImportError:
            return

        async for _changes in awatch(path):
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
            execution_mode=meta.get("execution_mode", DEFAULT_EXECUTION_MODE),
            execute_fn=execute_fn,
        )

    async def _load_python_tool(self, py_file: Path) -> JarvisTool | None:
        module = _load_module(py_file)

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and attr_name != "object" and hasattr(attr, "name"):
                try:
                    instance = attr()
                    if looks_like_tool(instance):
                        return instance  # type: ignore[no-any-return]  # 모양을 확인한 덕 타이핑 도구
                except Exception:
                    pass

        execute_fn = getattr(module, "execute", None)
        name = getattr(module, "TOOL_NAME", py_file.stem.replace("_", "-"))
        description = getattr(module, "TOOL_DESCRIPTION", "")
        parameters = getattr(module, "TOOL_PARAMETERS", default_parameters())

        if execute_fn:
            return _FunctionTool(
                name=name,
                description=description,
                parameters=parameters,
                execution_mode=DEFAULT_EXECUTION_MODE,
                execute_fn=execute_fn,
            )
        return None


def _load_module(py_file: Path) -> ModuleType:
    # 접두를 붙여 등록한다. 파일 이름 그대로(json.py 등) 넣으면 같은 이름의 표준 모듈을 덮는다
    module_name = f"{TOOL_MODULE_PREFIX}{py_file.stem}"
    spec = importlib.util.spec_from_file_location(module_name, py_file)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class _FunctionTool(JarvisTool):
    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        execution_mode: str,
        execute_fn: ToolFunction,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.execution_mode = execution_mode
        self._fn = execute_fn

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
    ) -> ToolResultMessage:
        try:
            result = await self._fn(tool_call_id=tool_call_id, params=params)
            content = result.get("content", str(result)) if isinstance(result, dict) else str(result)
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=content)],
            )
        except Exception as exc:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=str(exc))],
                is_error=True,
            )
