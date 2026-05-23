from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from jarvis.model_layer.types import AssistantMessage, Message, ModelConfig, StreamOptions, Tool

# ── Agent events (Pi: AgentEvent 패턴) ────────────────────────────────────────

class AgentStartEvent(BaseModel):
    type: Literal["agent_start"] = "agent_start"
    session_id: str
    prompt: str
    agent_name: str | None = None
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))


class TurnStartEvent(BaseModel):
    type: Literal["turn_start"] = "turn_start"
    turn: int
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))


class MessageUpdateEvent(BaseModel):
    type: Literal["message_update"] = "message_update"
    text_delta: str = ""
    thinking_delta: str = ""
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))


class ToolExecutionStartEvent(BaseModel):
    type: Literal["tool_execution_start"] = "tool_execution_start"
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))


class ToolExecutionEndEvent(BaseModel):
    type: Literal["tool_execution_end"] = "tool_execution_end"
    tool_call_id: str
    tool_name: str
    is_error: bool
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))


class AgentEndEvent(BaseModel):
    type: Literal["agent_end"] = "agent_end"
    session_id: str
    final_message: AssistantMessage | None = None
    turns: int = 0
    agent_name: str | None = None
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))


class AgentErrorEvent(BaseModel):
    type: Literal["agent_error"] = "agent_error"
    message: str
    code: str | None = None
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))


AgentEvent = (
    AgentStartEvent
    | TurnStartEvent
    | MessageUpdateEvent
    | ToolExecutionStartEvent
    | ToolExecutionEndEvent
    | AgentEndEvent
    | AgentErrorEvent
)


# ── Agent context & config ────────────────────────────────────────────────────

class AgentContext(BaseModel):
    session_id: str
    messages: list[Message] = Field(default_factory=list)
    tools: list[Tool] = Field(default_factory=list)
    model: ModelConfig
    system_prompt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentLoopConfig(BaseModel):
    max_turns: int = 20
    stream_options: StreamOptions = Field(default_factory=StreamOptions)
    tool_execution_mode: Literal["parallel", "sequential"] = "parallel"
    abort_on_error: bool = False
