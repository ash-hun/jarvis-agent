from __future__ import annotations

import asyncio
from pathlib import Path

import aiofiles

from jarvis.model_layer.types import TextContent, ToolResultMessage

TOOL_NAME = "read_file"
TOOL_DESCRIPTION = "Read the contents of a file."
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "File path to read"},
        "offset": {"type": "integer", "description": "Line number to start reading from (1-based)"},
        "limit": {"type": "integer", "description": "Maximum number of lines to read"},
    },
    "required": ["path"],
}


class ReadFileTool:
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
        path = Path(params["path"]).expanduser()
        offset = params.get("offset", 1)
        limit = params.get("limit")

        if not path.exists():
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=f"File not found: {path}")],
                is_error=True,
            )

        try:
            async with aiofiles.open(path, encoding="utf-8", errors="replace") as f:
                lines = await f.readlines()

            start = max(0, offset - 1)
            end = (start + limit) if limit else len(lines)
            selected = lines[start:end]

            numbered = "".join(f"{start + i + 1}\t{line}" for i, line in enumerate(selected))
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=numbered)],
            )
        except Exception as exc:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=str(exc))],
                is_error=True,
            )
