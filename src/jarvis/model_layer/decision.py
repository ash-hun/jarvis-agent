"""[model_layer] decision model(System One API, 예: Ollama 의 tev1, nimble)에 예/아니오 질문을 던져 확률을 받는다."""

import httpx
from typing import Any

from jarvis.common.logger import get_logger

DECISION_PATH = "/v1/systemone"
DECISION_TIMEOUT_SEC = 30.0

logger = get_logger(__name__)


class DecisionModel:
    """글을 쓰지 않고 주어진 선택지의 확률만 돌려주는 모델. 실패하면 None 으로 알린다."""

    def __init__(self, model: str, base_url: str, timeout: float = DECISION_TIMEOUT_SEC) -> None:
        self.model = model
        self._url = base_url.rstrip("/") + DECISION_PATH
        self._timeout = timeout

    async def yes_probability(self, state: dict[str, Any], instructions: str, no: str, yes: str) -> float | None:
        """state 에 대해 instructions 가 참일 확률(0~1). 호출이나 응답 형식이 틀리면 None."""
        body = {
            "model": self.model,
            "state": state,
            "questions": {"q": {"type": "noul", "instructions": instructions, "criteria": {"false": no, "true": yes}}},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._url, json=body)
                response.raise_for_status()
                value = response.json()["answers"]["q"]["noul"]
        except Exception as exc:
            logger.info(f"[Decision] {self.model} call failed: {exc!r}")
            return None
        return float(value) if isinstance(value, (int, float)) else None
