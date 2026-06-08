"""
User Model 서브시스템 (Tier 3 D1).

누적 기억에서 사용자의 안정적 특성(선호·작업 방식·반복 패턴)을 LLM으로 증류해
저장하고, 사고 시 컨텍스트로 주입해 "사용자를 아는" 판단을 돕는다.
"""
from __future__ import annotations

from jarvis.agent_layer.usermodel.builder import DEFAULT_PROMPT, UserModelBuilder
from jarvis.agent_layer.usermodel.store import (
    InMemoryUserModelStore,
    JsonlUserModelStore,
    UserModelStore,
)
from jarvis.agent_layer.usermodel.types import UserModel

__all__ = [
    "DEFAULT_PROMPT",
    "InMemoryUserModelStore",
    "JsonlUserModelStore",
    "UserModel",
    "UserModelBuilder",
    "UserModelStore",
]
