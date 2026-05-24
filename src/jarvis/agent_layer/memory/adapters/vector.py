from __future__ import annotations

from typing import Any, Callable

from jarvis.model_layer.types import Message


class VectorMemoryAdapter:
    """
    외부 벡터 DB (Chroma, Weaviate 등) 어댑터.
    chromadb는 optional dependency: pip install jarvis[vector-memory]
    """

    def __init__(
        self,
        collection_name: str = "jarvis_memory",
        embedding_fn: Callable[[str], list[float]] | None = None,
    ) -> None:
        self._collection_name = collection_name
        self._embedding_fn = embedding_fn
        self._client = None
        self._collection = None

    async def _ensure_init(self) -> None:
        if self._client is not None:
            return
        try:
            import chromadb
        except ImportError as exc:
            raise ImportError(
                "chromadb is required for VectorMemoryAdapter. "
                "Install with: pip install jarvis[vector-memory]"
            ) from exc
        self._client = chromadb.AsyncClient()
        self._collection = await self._client.get_or_create_collection(self._collection_name)

    async def transform(self, messages: list[Message], context: dict[str, Any]) -> list[Message]:
        return messages

    async def store(self, message: Message, context: dict[str, Any]) -> None:
        await self._ensure_init()
        text = message.model_dump_json()
        doc_id = f"{context.get('session_id', 'default')}-{message.timestamp}"
        embedding = self._embedding_fn(text) if self._embedding_fn else None
        kwargs: dict[str, Any] = {
            "documents": [text],
            "ids": [doc_id],
            "metadatas": [{"session_id": context.get("session_id", "default"), "role": message.role}],
        }
        if embedding:
            kwargs["embeddings"] = [embedding]
        await self._collection.add(**kwargs)  # type: ignore[union-attr]

    async def retrieve(self, query: str, context: dict[str, Any], limit: int = 10) -> list[Message]:
        await self._ensure_init()
        from jarvis.agent_layer.memory.backends.postgres_stm import _deserialize

        where = {"session_id": context.get("session_id", "default")}
        query_kwargs: dict[str, Any] = {"query_texts": [query], "n_results": limit, "where": where}
        if self._embedding_fn:
            query_kwargs = {"query_embeddings": [self._embedding_fn(query)], "n_results": limit, "where": where}

        results = await self._collection.query(**query_kwargs)  # type: ignore[union-attr]
        messages = []
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            import json
            data = json.loads(doc) if isinstance(doc, str) else doc
            msg = _deserialize(meta.get("role", "user"), data)
            if msg:
                messages.append(msg)
        return messages

    async def clear(self, context: dict[str, Any]) -> None:
        await self._ensure_init()
        sid = context.get("session_id", "default")
        results = await self._collection.get(where={"session_id": sid})  # type: ignore[union-attr]
        if results["ids"]:
            await self._collection.delete(ids=results["ids"])  # type: ignore[union-attr]
