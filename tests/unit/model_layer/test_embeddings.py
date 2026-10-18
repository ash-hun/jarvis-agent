"""임베딩 provider: 요청 모양과 응답 파싱을 MockTransport 로 검증. 실제 서버는 부르지 않는다."""

import json
import httpx
import pytest

from jarvis.model_layer.embeddings import OllamaEmbedder, OpenAIEmbedder, VLLMEmbedder, build_embedder, cosine


def test_cosine():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([], [1.0]) == 0.0 and cosine([1.0], [1.0, 2.0]) == 0.0


async def test_ollama_embed_posts_to_api_embed_and_parses():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["body"] = str(request.url), json.loads(request.content)
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]})

    embedder = OllamaEmbedder(model="nomic-embed-text", dimensions=2, transport=httpx.MockTransport(handler))
    vectors = await embedder.embed(["a", "b"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert seen["url"] == "http://localhost:11434/api/embed"
    assert seen["body"] == {"model": "nomic-embed-text", "input": ["a", "b"]}


async def test_vllm_embed_uses_openai_compatible_route_with_bearer():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers.get("authorization")
        return httpx.Response(
            200, json={"data": [{"index": 1, "embedding": [0.9]}, {"index": 0, "embedding": [0.1]}]}
        )

    embedder = VLLMEmbedder(
        model="bge", dimensions=1, base_url="http://vllm:8000/", api_key="k", transport=httpx.MockTransport(handler)
    )
    assert await embedder.embed(["x", "y"]) == [[0.1], [0.9]]  # index 순으로 정렬
    assert seen["url"] == "http://vllm:8000/v1/embeddings" and seen["auth"] == "Bearer k"


async def test_openai_embed_via_sdk_with_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "text-embedding-3-small" and body["dimensions"] == 3
        return httpx.Response(
            200,
            json={"object": "list", "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}],
                  "model": "text-embedding-3-small", "usage": {"prompt_tokens": 1, "total_tokens": 1}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    embedder = OpenAIEmbedder(api_key="sk", dimensions=3, http_client=client)
    assert await embedder.embed(["hi"]) == [[0.1, 0.2, 0.3]]


def test_build_embedder_from_config():
    assert build_embedder("") is None
    assert isinstance(build_embedder("openai", api_key="k"), OpenAIEmbedder)
    assert build_embedder("ollama").dimensions == 768
    assert build_embedder("vllm", model="bge", dimensions=1024).model == "bge"
    with pytest.raises(ValueError):
        build_embedder("vllm")
    with pytest.raises(ValueError):
        build_embedder("cohere")
