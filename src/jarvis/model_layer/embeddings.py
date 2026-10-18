"""[model_layer] 텍스트를 벡터로 바꾸는 임베딩 프로바이더로, 메모리 검색을 키워드에서 의미 유사도로 넓힌다."""

import math
import httpx

DEFAULT_TIMEOUT = 30.0


class Embedder:
    """임베딩 프로바이더의 기본 클래스. 하위 클래스가 model, dimensions 를 정하고 embed() 로 백엔드를 부른다."""

    model: str
    dimensions: int  # 저장소의 vector 컬럼 차원. 모델이 바뀌면 재임베딩이 필요하다

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("임베딩 백엔드는 하위 클래스가 정한다")


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class OpenAIEmbedder(Embedder):
    """OpenAI embeddings API. text-embedding-3-small 은 1536 차원."""

    def __init__(
        self,
        api_key: str | None,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._api_key = api_key
        self._base_url = base_url
        self._http_client = http_client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import openai

        client = openai.AsyncOpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            http_client=self._http_client,  # type: ignore[arg-type]  # httpx 와 httpx2 클라이언트 타입 불일치
        )
        response = await client.embeddings.create(input=texts, model=self.model, dimensions=self.dimensions)
        return [list(row.embedding) for row in response.data]


class OllamaEmbedder(Embedder):
    """Ollama /api/embed. nomic-embed-text 는 768 차원."""

    def __init__(
        self,
        model: str = "nomic-embed-text",
        dimensions: int = 768,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._base_url = (base_url or "http://localhost:11434").rstrip("/")
        self._transport = transport

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, transport=self._transport) as client:
            resp = await client.post(f"{self._base_url}/api/embed", json={"model": self.model, "input": texts})
            resp.raise_for_status()
            return [list(map(float, row)) for row in resp.json()["embeddings"]]


class VLLMEmbedder(Embedder):
    """vLLM 의 OpenAI 호환 /v1/embeddings. 차원은 서빙 모델에 따른다."""

    def __init__(
        self,
        model: str,
        dimensions: int,
        base_url: str | None = None,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._base_url = (base_url or "http://localhost:8000").rstrip("/")
        self._api_key = api_key
        self._transport = transport

    async def embed(self, texts: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, transport=self._transport) as client:
            resp = await client.post(
                f"{self._base_url}/v1/embeddings", json={"model": self.model, "input": texts}, headers=headers
            )
            resp.raise_for_status()
            rows = sorted(resp.json()["data"], key=lambda r: r.get("index", 0))
            return [list(map(float, row["embedding"])) for row in rows]


def build_embedder(
    provider: str,
    model: str = "",
    dimensions: int = 0,
    api_key: str | None = None,
    base_url: str | None = None,
) -> Embedder | None:
    """설정 → Embedder. provider 가 비어 있으면 None(키워드 검색만)."""
    provider = (provider or "").strip().lower()
    if not provider:
        return None
    if provider == "openai":
        return OpenAIEmbedder(
            api_key=api_key, model=model or "text-embedding-3-small", dimensions=dimensions or 1536, base_url=base_url
        )
    if provider == "ollama":
        return OllamaEmbedder(model=model or "nomic-embed-text", dimensions=dimensions or 768, base_url=base_url)
    if provider == "vllm":
        if not model or not dimensions:
            raise ValueError("vllm embedder needs JARVIS_MEMORY__EMBEDDING_MODEL and EMBEDDING_DIMENSIONS")
        return VLLMEmbedder(model=model, dimensions=dimensions, base_url=base_url, api_key=api_key)
    raise ValueError(f"unknown embedding provider: {provider!r} (openai | ollama | vllm)")
