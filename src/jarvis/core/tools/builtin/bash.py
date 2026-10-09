from __future__ import annotations

import asyncio

from jarvis.model_layer.types import TextContent, ToolResultMessage

TOOL_NAME = "bash"
TOOL_DESCRIPTION = "Execute a bash command and return stdout/stderr. Use with caution."
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "The bash command to execute"},
        "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)", "default": 30},
    },
    "required": ["command"],
}


class BashTool:
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
        command = params["command"]
        timeout = params.get("timeout", 30)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except TimeoutError:
                proc.kill()
                return ToolResultMessage(
                    tool_call_id=tool_call_id,
                    tool_name=self.name,
                    content=[TextContent(text=f"Command timed out after {timeout}s")],
                    is_error=True,
                )

            output = stdout.decode("utf-8", errors="replace")
            error = stderr.decode("utf-8", errors="replace")
            is_error = proc.returncode != 0
            text = output + (f"\n[stderr]\n{error}" if error else "")

            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=text or "(no output)")],
                is_error=is_error,
            )
        except Exception as exc:
            return ToolResultMessage(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                content=[TextContent(text=str(exc))],
                is_error=True,
            )
