from __future__ import annotations

import asyncio
from pathlib import Path

from jarvis.model_layer.types import TextContent, ToolResultMessage

TOOL_NAME = "glob"
TOOL_DESCRIPTION = (
    "Find files by glob pattern (e.g. '**/*.py', 'src/**/test_*.py'). "
    "Returns matching file paths sorted by most-recently-modified first. "
    "Use this to locate files by name without running shell commands."
)
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "pattern": {
            "type": "string",
            "description": "Glob pattern, e.g. '**/*.py'. Supports recursive '**'.",
        },
        "path": {
            "type": "string",
            "description": "Root directory to search from (default: current directory)",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of paths to return (default: 100)",
        },
    },
    "required": ["pattern"],
}


class GlobTool:
    name = TOOL_NAME
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS
    execution_mode = "parallel"

    async def execute(
        self,
        tool_call_id: str,
        params: dict,
        signal: asyncio.Event | None = None,
    ) -> ToolResultMessage:
        pattern = params["pattern"]
        root = Path(params.get("path", ".")).expanduser()
        limit = int(params.get("limit", 100))

        if not root.exists():
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=f"Directory not found: {root}")],
                is_error=True,
            )

        try:
            matches = await asyncio.to_thread(_glob, root, pattern, limit)
        except Exception as exc:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=str(exc))],
                is_error=True,
            )

        if not matches:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=f"No files matching: {pattern}")],
            )

        header = f"{len(matches)} match(es) for '{pattern}':\n"
        body = "\n".join(str(p) for p in matches)
        return ToolResultMessage(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            content=[TextContent(text=header + body)],
        )


def _glob(root: Path, pattern: str, limit: int) -> list[Path]:
    """파일만 매칭해 mtime 내림차순으로 정렬, limit개 반환."""
    files = [p for p in root.glob(pattern) if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]
