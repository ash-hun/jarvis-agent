"""[scripts] 도구 디렉터리에 파일을 쓰고 그 도구를 부를 수 있게 되기까지의 시간을 파일 감시와 재시작으로 잰다."""

import os
import sys
import json
import time
import asyncio
import argparse
import tempfile
import statistics
import subprocess
from typing import Any
from pathlib import Path

os.environ.setdefault("JARVIS_LLM__PROVIDER", "faux")
os.environ.setdefault("JARVIS_LOG_LEVEL", "WARNING")

from jarvis.core.tools.tools_registry import ToolRegistry
from jarvis.core.tools.tools_loader import ToolLoader
import jarvis

RESULTS = Path(__file__).resolve().parent / "results.json"
KEY = "tool_reload"
REPEATS = 30
RESTART_REPEATS = 10
STATIC_WAIT_SEC = 5.0  # 감시가 없는 코드에서 새 도구를 기다려 보는 시간
TIMEOUT_SEC = 10.0
SAME_SIZE_WAIT_SEC = 3.0
POLL_SEC = 0.002
TOOL_SOURCE = '''TOOL_NAME = "{name}"
TOOL_DESCRIPTION = "{description}"


async def execute(tool_call_id, params):
    return {{"content": "{reply}"}}
'''
# 재시작 한 번: 새 파이썬 프로세스가 앱을 조립하고(도구 디렉터리 읽기 포함) 그 도구가 레지스트리에 있는지 본다
RESTART_CHILD = """
import os
from jarvis.jarvis_config import JarvisSettings
JarvisSettings.model_config["env_file"] = None
from jarvis.app.infra_builder import build_app
assembly = build_app(JarvisSettings())
assert assembly.ctx.tool_registry.get(os.environ["WANT_TOOL"]) is not None
"""


def _write_tool(directory: Path, name: str, description: str) -> None:
    # 다른 이름 임시 파일에 다 쓴 뒤 바꿔 끼운다. 반쯤 쓴 파일을 감시가 읽지 않게(편집기의 저장과 같다)
    tmp = directory / f".{name}.tmp"
    tmp.write_text(TOOL_SOURCE.format(name=name, description=description, reply=description), encoding="utf-8")
    tmp.replace(directory / f"{name}.py")


async def _wait_until(check: Any, timeout: float = TIMEOUT_SEC) -> float | None:
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        if check():
            return time.perf_counter() - start
        await asyncio.sleep(POLL_SEC)
    return None


async def _callable_text(registry: ToolRegistry, name: str) -> str:
    tool = registry.get(name)
    assert tool is not None
    result = await tool.execute("c", {})
    return "".join(getattr(c, "text", "") for c in result.content)


def _summary(samples: list[float | None]) -> dict[str, Any]:
    ok = sorted(s * 1000 for s in samples if s is not None)
    if not ok:
        return {"runs": len(samples), "timeouts": len(samples)}
    return {
        "runs": len(samples),
        "timeouts": len(samples) - len(ok),
        "p50_ms": round(statistics.median(ok), 1),
        "p95_ms": round(ok[min(len(ok) - 1, int(0.95 * len(ok)))], 1),
        "max_ms": round(ok[-1], 1),
    }


async def watch_mode() -> dict[str, Any]:
    from jarvis.app.extension_watcher import ExtensionWatcher

    with tempfile.TemporaryDirectory() as root:
        tools_dir = Path(root) / "tools"
        tools_dir.mkdir()
        registry = ToolRegistry()
        watcher = ExtensionWatcher({str(tools_dir): ToolLoader(registry).load_directory})
        await watcher.start()
        await asyncio.sleep(1.0)  # awatch 가 감시를 걸 때까지
        added: list[float | None] = []
        changed: list[float | None] = []
        same_size: list[float | None] = []
        called = 0
        try:
            for i in range(REPEATS):
                name = f"exp_tool_{i}"
                _write_tool(tools_dir, name, "v1")
                added.append(await _wait_until(lambda n=name: registry.get(n) is not None))  # type: ignore[misc]
                await asyncio.sleep(0.3)
                _write_tool(tools_dir, name, "v2 edited")
                changed.append(await _wait_until(lambda n=name: _description(registry, n) == "v2 edited"))  # type: ignore[misc]
                called += await _callable_text(registry, name) == "v2 edited"
                await asyncio.sleep(0.3)
                # 길이가 같은 수정(한 글자 바꾸기)을 1초 안에 다시 한다. .pyc 는 파일 크기와 초 단위 mtime 으로 검사한다
                _write_tool(tools_dir, name, "v3 edited")
                same_size.append(
                    await _wait_until(lambda n=name: _description(registry, n) == "v3 edited", SAME_SIZE_WAIT_SEC)  # type: ignore[misc]
                )
                await asyncio.sleep(0.3)
        finally:
            await watcher.stop()
    return {
        "new_file": _summary(added),
        "modified_file": _summary(changed),
        "called_after_change": f"{called}/{REPEATS}",
        "same_size_edit_seen": f"{sum(s is not None for s in same_size)}/{REPEATS}",
        "same_size_wait_s": SAME_SIZE_WAIT_SEC,
    }


def _description(registry: ToolRegistry, name: str) -> str:
    return str(getattr(registry.get(name), "description", ""))


async def static_mode() -> dict[str, Any]:
    """감시가 없는 코드: 기동 때 한 번 읽고, 그 뒤에 쓴 도구가 STATIC_WAIT_SEC 안에 보이는지."""
    with tempfile.TemporaryDirectory() as root:
        tools_dir = Path(root) / "tools"
        tools_dir.mkdir()
        _write_tool(tools_dir, "exp_tool_boot", "boot")
        registry = ToolRegistry()
        await ToolLoader(registry).load_directory(str(tools_dir))
        _write_tool(tools_dir, "exp_tool_late", "late")
        await asyncio.sleep(STATIC_WAIT_SEC)
        seen = registry.get("exp_tool_late") is not None
    return {"boot_tool_loaded": registry.get("exp_tool_boot") is not None, "late_tool_visible_after_s": STATIC_WAIT_SEC,
            "late_tool_visible": seen}


def restart_mode() -> dict[str, Any]:
    samples: list[float | None] = []
    with tempfile.TemporaryDirectory() as root:
        home = Path(root) / "home"
        tools_dir = home / ".jarvis" / "tools"
        tools_dir.mkdir(parents=True)
        _write_tool(tools_dir, "exp_tool_restart", "r")
        env = {
            **os.environ, "HOME": str(home), "WANT_TOOL": "exp_tool_restart",
            "JARVIS_MEMORY__BACKEND": "in_memory", "JARVIS_SESSION__PERSISTENCE_BACKEND": "jsonl",
            "JARVIS_PROACTIVE__DAEMON_ENABLED": "false", "JARVIS_SCHEDULER__ENABLED": "false",
        }
        for _ in range(RESTART_REPEATS):
            start = time.perf_counter()
            done = subprocess.run([sys.executable, "-c", RESTART_CHILD], env=env, cwd=root, capture_output=True,
                                  timeout=120)
            took = time.perf_counter() - start
            if done.returncode != 0:
                raise RuntimeError(done.stderr.decode()[-2000:])
            samples.append(took)
    return {"restart": _summary(samples)}


def write(label: str, result: dict[str, Any]) -> None:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    data.setdefault(KEY, {}).setdefault(label, {}).update(result)
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, help="results.json 의 tool_reload 아래 키(코드 시점)")
    parser.add_argument("--mode", choices=("watch", "static", "restart"), required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(f"jarvis from {jarvis.__file__}", file=sys.stderr)
    if args.mode == "watch":
        result = asyncio.run(watch_mode())
    elif args.mode == "static":
        result = asyncio.run(static_mode())
    else:
        result = restart_mode()
    print(json.dumps(result, ensure_ascii=False))
    if not args.dry_run:
        write(args.label, {args.mode: result})


if __name__ == "__main__":
    main()
