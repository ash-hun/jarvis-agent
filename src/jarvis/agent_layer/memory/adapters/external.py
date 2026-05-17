from __future__ import annotations

from typing import Any, Callable, Awaitable

from jarvis.model_layer.types import Message


class ExternalDBMemory:
    """
    완전 커스텀 외부 DB 어댑터.
    store_fn, retrieve_fn을 주입하여 어떤 DB든 연결 가능.
    """

    def __init__(
        self,
        store_fn: Callable[[Message, dict[str, Any]], Awaitable[None]],
        retrieve_fn: Callable[[str, dict[str, Any], int], Awaitable[list[Message]]],
        transform_fn: Callable[[list[Message], dict[str, Any]], Awaitable[list[Message]]] | None = None,
        clear_fn: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self._store_fn = store_fn
        self._retrieve_fn = retrieve_fn
        self._transform_fn = transform_fn
        self._clear_fn = clear_fn

    async def transform(self, messages: list[Message], context: dict[str, Any]) -> list[Message]:
        if self._transform_fn:
            return await self._transform_fn(messages, context)
        return messages

    async def store(self, message: Message, context: dict[str, Any]) -> None:
        await self._store_fn(message, context)

    async def retrieve(self, query: str, context: dict[str, Any], limit: int = 10) -> list[Message]:
        return await self._retrieve_fn(query, context, limit)

    async def clear(self, context: dict[str, Any]) -> None:
        if self._clear_fn:
            await self._clear_fn(context)
