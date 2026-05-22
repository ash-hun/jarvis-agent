from __future__ import annotations

import asyncio
from pathlib import Path

import aiofiles

from jarvis.model_layer.types import TextContent, ToolResultMessage

TOOL_NAME = "write_file"
TOOL_DESCRIPTION = "Write content to a file, creating parent directories if needed. Overwrites existing content."
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "File path to write"},
        "content": {"type": "string", "description": "Content to write"},
        "encoding": {"type": "string", "description": "File encoding (default: utf-8)"},
    },
    "required": ["path", "content"],
}


class WriteFileTool:
    name = TOOL_NAME
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS
    execution_mode = "sequential"

    async def execute(
        self,
        tool_call_id: str,
        params: dict,
        signal: asyncio.Event | None = None,
    ) -> ToolResultMessage:
        path = Path(params["path"]).expanduser()
        content = params["content"]
        encoding = params.get("encoding", "utf-8")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(path, "w", encoding=encoding) as f:
                await f.write(content)
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=f"Wrote {len(content)} chars to {path}")],
            )
        except Exception as exc:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=str(exc))],
                is_error=True,
            )
