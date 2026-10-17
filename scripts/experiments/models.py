"""[scripts] 실험에서 비교하는 모델 정의. 로컬은 Ollama, 클라우드 키는 설정(.env)에서 읽는다."""

import os

from jarvis.config import get_settings
from jarvis.model_layer.types import ModelConfig

OLLAMA_URL = os.environ.get("EXPERIMENT_OLLAMA_URL", "http://localhost:11434")
LOCAL = {
    "gemma4:e2b-it-qat": "ollama",
    "gemma4:e4b": "ollama",
}
CLOUD = {"gpt-4o-mini": "openai"}


def model_config(name: str) -> ModelConfig:
    """이름 하나로 ModelConfig. 로컬은 Ollama 주소, 클라우드는 설정의 API 키를 쓴다."""
    if name in LOCAL:
        return ModelConfig(provider="ollama", model=name, base_url=OLLAMA_URL, timeout=120.0)
    if name in CLOUD:
        secret = get_settings().llm.api_key
        key = secret.get_secret_value() if secret else None
        return ModelConfig(provider=CLOUD[name], model=name, api_key=key, timeout=120.0)
    raise SystemExit(f"모르는 모델: {name}")
