from __future__ import annotations

import asyncio
from pathlib import Path

import aiofiles

from jarvis.model_layer.types import TextContent, ToolResultMessage

TOOL_NAME = "edit_file"
TOOL_DESCRIPTION = (
    "Replace an exact string in a file. "
    "Fails if old_string is not found. "
    "Set replace_all=true to replace every occurrence; otherwise fails when multiple matches exist."
)
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "File path to edit"},
        "old_string": {"type": "string", "description": "Exact string to replace"},
        "new_string": {"type": "string", "description": "Replacement string"},
        "replace_all": {
            "type": "boolean",
            "description": "Replace all occurrences (default: false)",
            "default": False,
        },
    },
    "required": ["path", "old_string", "new_string"],
}


class EditFileTool:
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
        old_string = params["old_string"]
        new_string = params["new_string"]
        replace_all = params.get("replace_all", False)

        if not path.exists():
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=f"File not found: {path}")],
                is_error=True,
            )

        try:
            async with aiofiles.open(path, encoding="utf-8", errors="replace") as f:
                original = await f.read()

            count = original.count(old_string)
            if count == 0:
                return ToolResultMessage(
                    tool_call_id=tool_call_id,
                    tool_name=self.name,
                    content=[TextContent(text=f"old_string not found in {path}")],
                    is_error=True,
                )
            if count > 1 and not replace_all:
                return ToolResultMessage(
                    tool_call_id=tool_call_id,
                    tool_name=self.name,
                    content=[TextContent(
                        text=(
                            f"old_string found {count} times in {path}; "
                            "set replace_all=true to replace all occurrences"
                        )
                    )],
                    is_error=True,
                )

            replaced_count = count if replace_all else 1
            updated = original.replace(old_string, new_string, -1 if replace_all else 1)

            async with aiofiles.open(path, "w", encoding="utf-8") as f:
                await f.write(updated)

            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=f"Replaced {replaced_count} occurrence(s) in {path}")],
            )
        except Exception as exc:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=str(exc))],
                is_error=True,
            )
