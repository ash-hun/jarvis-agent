"""[core] 디렉터리 항목을 종류와 크기와 함께 나열하는 list_dir 내장 도구."""

import asyncio
from typing import Any
from pathlib import Path

from jarvis.model_layer.model_types import TextContent, ToolResultMessage
from jarvis.core.tools.tools_registry import JarvisTool

TOOL_NAME = "list_dir"
TOOL_DESCRIPTION = (
    "List the contents of a directory. Returns each entry with its type "
    "(dir/file) and size. Use this to explore directory structure without "
    "running shell commands."
)
TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Directory path to list (default: current directory)",
        },
        "all": {
            "type": "boolean",
            "description": "Include hidden entries (dotfiles) (default: false)",
        },
    },
    "required": [],
}


class ListDirTool(JarvisTool):
    name = TOOL_NAME
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS
    execution_mode = "parallel"

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: asyncio.Event | None = None,
    ) -> ToolResultMessage:
        path = Path(params.get("path", ".")).expanduser()
        show_all = bool(params.get("all", False))

        if not path.exists():
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=f"Directory not found: {path}")],
                is_error=True,
            )
        if not path.is_dir():
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=f"Not a directory: {path}")],
                is_error=True,
            )

        try:
            lines = await asyncio.to_thread(_list_dir, path, show_all)
        except Exception as exc:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=str(exc))],
                is_error=True,
            )

        header = f"{path} ({len(lines)} entries):\n"
        return ToolResultMessage(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            content=[TextContent(text=header + "\n".join(lines))],
        )


def _list_dir(path: Path, show_all: bool) -> list[str]:
    entries = sorted(
        path.iterdir(),
        key=lambda p: (p.is_file(), p.name.lower()),  # 디렉토리 먼저, 이름순
    )
    lines: list[str] = []
    for entry in entries:
        if not show_all and entry.name.startswith("."):
            continue
        if entry.is_dir():
            lines.append(f"  dir   {entry.name}/")
        else:
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            lines.append(f"  file  {entry.name}  ({_human_size(size)})")
    return lines


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}GB"
