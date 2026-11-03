"""[scripts] 실험에서 비교하는 모델 정의. 로컬은 Ollama, 클라우드 키는 provider 마다 환경변수나 .env 에서 읽는다."""

import os
from pathlib import Path
from dotenv import dotenv_values

from jarvis.model_layer.model_types import ModelConfig
from jarvis.jarvis_config import get_settings

OLLAMA_URL = os.environ.get("EXPERIMENT_OLLAMA_URL", "http://localhost:11434")
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
LOCAL = {
    "gemma4:e2b-it-qat": "ollama",
    "gemma4:e4b": "ollama",
}
CLOUD = {
    "gpt-4o-mini": "openai",
    "gpt-4o": "openai",
    "claude-sonnet-5-5": "anthropic",
    "claude-haiku-5-5": "anthropic",
}
# 메인 LLM 키(JARVIS_LLM__API_KEY)와 provider 가 다른 모델은 이 이름의 키를 쓴다
PROVIDER_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


def api_key(provider: str) -> str | None:
    """provider 키. 메인 LLM 과 같은 provider 면 설정의 키, 아니면 PROVIDER_KEYS 이름의 환경변수, 그다음 .env."""
    settings = get_settings()
    if settings.llm.provider == provider and settings.llm.api_key:
        return settings.llm.api_key.get_secret_value()
    name = PROVIDER_KEYS.get(provider, "")
    # 다른 provider 의 키로 대신 부르지 않는다. 없으면 None 이라 호출이 인증 오류로 드러난다
    return os.environ.get(name) or (dotenv_values(ENV_FILE).get(name) if ENV_FILE.exists() else None)


def model_config(name: str) -> ModelConfig:
    """이름 하나로 ModelConfig. 로컬은 Ollama 주소, 클라우드는 provider 의 API 키를 쓴다."""
    if name in LOCAL:
        return ModelConfig(provider="ollama", model=name, base_url=OLLAMA_URL, timeout=120.0)
    if name in CLOUD:
        return ModelConfig(provider=CLOUD[name], model=name, api_key=api_key(CLOUD[name]), timeout=120.0)
    raise SystemExit(f"모르는 모델: {name}")
