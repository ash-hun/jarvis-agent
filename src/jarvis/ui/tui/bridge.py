from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from jarvis.agent_layer.types import (
    AgentEndEvent,
    AgentErrorEvent,
    AgentEvent,
    AgentStartEvent,
    InnerThoughtEvent,
    MessageUpdateEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
)

# ── UIAction 타입 (Hunk: Explicit Intent Encoding) ─────────────────────────────


@dataclass(frozen=True)
class ShowStatusAction:
    text: str
    kind: Literal["show_status"] = field(default="show_status", init=False)


@dataclass(frozen=True)
class AppendStreamAction:
    delta: str
    kind: Literal["append_stream"] = field(default="append_stream", init=False)


@dataclass(frozen=True)
class FlushStreamAction:
    kind: Literal["flush_stream"] = field(default="flush_stream", init=False)


@dataclass(frozen=True)
class ToolStartAction:
    tool_call_id: str
    tool_name: str
    kind: Literal["tool_start"] = field(default="tool_start", init=False)


@dataclass(frozen=True)
class ToolEndAction:
    tool_call_id: str
    tool_name: str
    is_error: bool
    kind: Literal["tool_end"] = field(default="tool_end", init=False)


@dataclass(frozen=True)
class ShowErrorAction:
    message: str
    kind: Literal["show_error"] = field(default="show_error", init=False)


@dataclass(frozen=True)
class InnerThoughtAction:
    """inner thought(메타인지) 산출물 — 메인 응답과 구분된 사고 라인으로 표시."""
    interpretation: str
    decision: str
    confidence: float
    kind: Literal["inner_thought"] = field(default="inner_thought", init=False)


@dataclass(frozen=True)
class AgentPushAction:
    """서브 에이전트 시작 — 계층 스택에 push."""
    agent_name: str
    kind: Literal["agent_push"] = field(default="agent_push", init=False)


@dataclass(frozen=True)
class AgentPopAction:
    """서브 에이전트 종료 — 계층 스택에서 pop."""
    agent_name: str | None
    kind: Literal["agent_pop"] = field(default="agent_pop", init=False)


UIAction = (
    ShowStatusAction
    | AppendStreamAction
    | FlushStreamAction
    | ToolStartAction
    | ToolEndAction
    | ShowErrorAction
    | InnerThoughtAction
    | AgentPushAction
    | AgentPopAction
)


# ── EventBridge ────────────────────────────────────────────────────────────────


class EventBridge:
    """
    AgentEvent → UIAction 번역 레이어. 상태 없음 — 순수 번역기.
    Hunk: Session Bridge 패턴 (bridge.ts).
    스트림 버퍼 상태는 JarvisTUI가 관리.
    """

    def translate(self, event: AgentEvent) -> list[UIAction]:
        """단일 AgentEvent를 0~N개의 UIAction으로 번역."""
        if isinstance(event, AgentStartEvent):
            name = event.agent_name or "agent"
            return [AgentPushAction(agent_name=name)]

        if isinstance(event, MessageUpdateEvent):
            actions: list[UIAction] = []
            if event.text_delta:
                actions.append(AppendStreamAction(delta=event.text_delta))
            return actions

        if isinstance(event, AgentEndEvent):
            return [
                FlushStreamAction(),
                AgentPopAction(agent_name=event.agent_name),
            ]

        if isinstance(event, ToolExecutionStartEvent):
            return [
                ToolStartAction(
                    tool_call_id=event.tool_call_id,
                    tool_name=event.tool_name,
                )
            ]

        if isinstance(event, ToolExecutionEndEvent):
            return [
                ToolEndAction(
                    tool_call_id=event.tool_call_id,
                    tool_name=event.tool_name,
                    is_error=event.is_error,
                ),
                ShowStatusAction(text="Thinking..."),
            ]

        if isinstance(event, InnerThoughtEvent):
            return [
                InnerThoughtAction(
                    interpretation=event.interpretation,
                    decision=event.decision,
                    confidence=event.confidence,
                )
            ]

        if isinstance(event, AgentErrorEvent):
            return [ShowErrorAction(message=event.message)]

        # TurnStartEvent 등 UI 처리 불필요 이벤트
        return []
