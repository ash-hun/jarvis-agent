"""[core] 외부 트리거(Proactive Phase 3) 패키지. 캘린더, 메일 등 외부 변화를 사고에 먹인다."""

# 소스 YAML이 없으면 전 구간 no-op. 발화 게이팅은 기존 proactive policy를 그대로 쓴다.

from jarvis.core.external.dedup import (
    InMemorySeenStore,
    JsonlSeenStore,
    SeenStore,
    derive_events,
)
from jarvis.core.external.loader import ExternalSourceSpec, load_source_specs
from jarvis.core.external.mcp_source import McpToolSource, build_mcp_sources
from jarvis.core.external.poller import ExternalEventPoller
from jarvis.core.external.inbox import ExternalEventInbox
from jarvis.core.external.protocol import ExternalSource
from jarvis.core.external.types import ExternalEvent

__all__ = [
    "ExternalEvent",
    "ExternalEventInbox",
    "ExternalEventPoller",
    "ExternalSource",
    "ExternalSourceSpec",
    "InMemorySeenStore",
    "JsonlSeenStore",
    "McpToolSource",
    "SeenStore",
    "build_mcp_sources",
    "derive_events",
    "load_source_specs",
]
