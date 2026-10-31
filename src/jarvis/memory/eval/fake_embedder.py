"""[memory] 토큰을 동의어 사전으로 정규화해 고정 차원에 해싱하는 결정론 임베더(배선 검증용, 품질 평가 아님)."""

import hashlib

from jarvis.memory.stores.store_protocol import tokens_of
from jarvis.model_layer.embeddings import Embedder

DIMENSIONS = 64

# 평가 사례가 쓰는 작은 동의어 사전. 실제 임베딩 모델이 잡아 줄 의역을 흉내 낸다
SYNONYMS = {
    "사는": "거주지", "곳": "", "거주": "거주지", "집": "거주지", "거주지": "거주지",
    "회사": "직장", "소속": "직장", "직장": "직장", "다니는": "",
    "강아지": "반려견", "개": "반려견", "반려견": "반려견",
    "마감": "마감", "데드라인": "마감", "기한": "마감",
}


def canonical_tokens(text: str) -> list[str]:
    out: list[str] = []
    for token in tokens_of(text):
        token = token.strip(":")
        token = SYNONYMS.get(token, token)
        if token:
            out.append(token)
    return out


class FakeEmbedder(Embedder):
    model = "fake-bow-64"
    dimensions = DIMENSIONS

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * DIMENSIONS
            for token in canonical_tokens(text):
                index = int(hashlib.md5(token.encode()).hexdigest(), 16) % DIMENSIONS
                vector[index] += 1.0
            vectors.append(vector)
        return vectors
