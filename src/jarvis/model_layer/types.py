from __future__ import annotations

import time
from typing import Any, AsyncIterator, Literal, Protocol, Union
from pydantic import BaseModel, Field


# ── Content blocks ────────────────────────────────────────────────────────────

class TextContent(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ThinkingContent(BaseModel):
    type: Literal["thinking"] = "thinking"
    thinking: str
    redacted: bool = False


class ImageContent(BaseModel):
    type: Literal["image"] = "image"
    data: str
    mime_type: str


class ToolCall(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    arguments: dict[str, Any]


# ── Messages ──────────────────────────────────────────────────────────────────

class Usage(BaseModel):
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output


StopReason = Literal["stop", "length", "tool_use", "error", "aborted"]


class UserMessage(BaseModel):
    role: Literal["user"] = "user"
    content: str | list[TextContent | ImageContent]
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))


class AssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: list[TextContent | ThinkingContent | ToolCall] = Field(default_factory=list)
    provider: str = ""
    model: str = ""
    usage: Usage = Field(default_factory=Usage)
    stop_reason: StopReason = "stop"
    error_message: str | None = None
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))

    def text(self) -> str:
        return "".join(block.text for block in self.content if isinstance(block, TextContent))

    def tool_calls(self) -> list[ToolCall]:
        return [block for block in self.content if isinstance(block, ToolCall)]


class ToolResultMessage(BaseModel):
    role: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    tool_name: str
    content: list[TextContent | ImageContent]
    is_error: bool = False
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))


Message = Union[UserMessage, AssistantMessage, ToolResultMessage]


# ── Streaming events (Pi: AssistantMessageEvent 패턴) ─────────────────────────

class TextDeltaEvent(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    delta: str


class ThinkingDeltaEvent(BaseModel):
    type: Literal["thinking_delta"] = "thinking_delta"
    thinking: str


class ToolCallDeltaEvent(BaseModel):
    type: Literal["tool_call_delta"] = "tool_call_delta"
    id: str
    name: str
    arguments_delta: str


class StopEvent(BaseModel):
    type: Literal["stop"] = "stop"
    reason: StopReason
    usage: Usage = Field(default_factory=Usage)


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
    code: str | None = None


StreamEvent = Union[
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallDeltaEvent,
    StopEvent,
    ErrorEvent,
]


# ── Tool definition ───────────────────────────────────────────────────────────

class ToolParameter(BaseModel):
    type: str
    description: str | None = None
    enum: list[str] | None = None
    items: dict[str, Any] | None = None
    properties: dict[str, Any] | None = None
    required: list[str] | None = None


class Tool(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]
    execution_mode: Literal["parallel", "sequential"] = "parallel"

    def to_llm_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


# ── LLM request context ───────────────────────────────────────────────────────

class ModelConfig(BaseModel):
    provider: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 120.0


class StreamOptions(BaseModel):
    enable_thinking: bool = False
    thinking_budget: int = 10_000
    system_prompt: str | None = None
    stop_sequences: list[str] = Field(default_factory=list)


class LLMContext(BaseModel):
    messages: list[Message]
    tools: list[Tool] | None = None
    system_prompt: str | None = None


# ── Provider Protocol ─────────────────────────────────────────────────────────

class ProviderStreamFn(Protocol):
    def __call__(
        self,
        model: ModelConfig,
        context: LLMContext,
        options: StreamOptions | None = None,
    ) -> AsyncIterator[StreamEvent]: ...
