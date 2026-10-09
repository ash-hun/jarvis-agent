"""agent_layer/memory/ — 메모리 미들웨어 체인 테스트."""
from __future__ import annotations

from jarvis.agent_layer.memory.chain import MemoryMiddlewareChain
from jarvis.agent_layer.memory.in_memory import WindowMemory
from jarvis.model_layer.types import UserMessage


def _make_messages(n: int) -> list:
    return [UserMessage(content=f"msg {i}") for i in range(n)]


class TestWindowMemory:
    async def test_transform_within_window(self):
        memory = WindowMemory(max_messages=10)
        messages = _make_messages(5)
        result = await memory.transform(messages, {})
        assert len(result) == 5

    async def test_transform_exceeds_window(self):
        memory = WindowMemory(max_messages=3)
        messages = _make_messages(10)
        result = await memory.transform(messages, {})
        assert len(result) == 3
        assert result[0].content == "msg 7"

    async def test_store_and_retrieve(self):
        memory = WindowMemory(max_messages=10)
        ctx = {"session_id": "test-01"}
        msg = UserMessage(content="stored message")
        await memory.store(msg, ctx)
        retrieved = await memory.retrieve("anything", ctx, limit=10)
        assert len(retrieved) == 1
        assert retrieved[0].content == "stored message"

    async def test_clear(self):
        memory = WindowMemory(max_messages=10)
        ctx = {"session_id": "test-02"}
        await memory.store(UserMessage(content="hello"), ctx)
        await memory.clear(ctx)
        retrieved = await memory.retrieve("anything", ctx)
        assert len(retrieved) == 0

    async def test_separate_sessions(self):
        memory = WindowMemory(max_messages=10)
        ctx_a = {"session_id": "session-a"}
        ctx_b = {"session_id": "session-b"}
        await memory.store(UserMessage(content="msg-a"), ctx_a)
        await memory.store(UserMessage(content="msg-b"), ctx_b)

        retrieved_a = await memory.retrieve("x", ctx_a)
        retrieved_b = await memory.retrieve("x", ctx_b)
        assert retrieved_a[0].content == "msg-a"
        assert retrieved_b[0].content == "msg-b"


class TestMemoryMiddlewareChain:
    async def test_chain_applies_stages_in_order(self):
        class PrefixMiddleware:
            async def transform(self, messages, context):
                return [UserMessage(content="prefix-" + m.content) for m in messages]
            async def store(self, message, context): pass
            async def retrieve(self, query, context, limit=10): return []
            async def clear(self, context): pass

        class UpperMiddleware:
            async def transform(self, messages, context):
                return [UserMessage(content=m.content.upper()) for m in messages]
            async def store(self, message, context): pass
            async def retrieve(self, query, context, limit=10): return []
            async def clear(self, context): pass

        chain = MemoryMiddlewareChain(stages=[PrefixMiddleware(), UpperMiddleware()])
        messages = [UserMessage(content="hello")]
        result = await chain.transform(messages, {})

        assert result[0].content == "PREFIX-HELLO"

    async def test_store_propagates_to_all_stages(self):
        stored = []

        class RecordingMiddleware:
            def __init__(self, name):
                self.name = name
            async def transform(self, messages, context): return messages
            async def store(self, message, context):
                stored.append(self.name)
            async def retrieve(self, query, context, limit=10): return []
            async def clear(self, context): pass

        chain = MemoryMiddlewareChain(stages=[
            RecordingMiddleware("A"),
            RecordingMiddleware("B"),
        ])
        await chain.store(UserMessage(content="test"), {})
        assert "A" in stored
        assert "B" in stored

    async def test_empty_chain_passthrough(self):
        chain = MemoryMiddlewareChain(stages=[])
        messages = _make_messages(3)
        result = await chain.transform(messages, {})
        assert result == messages

    async def test_window_memory_chain(self):
        chain = MemoryMiddlewareChain(stages=[WindowMemory(max_messages=5)])
        messages = _make_messages(20)
        result = await chain.transform(messages, {})
        assert len(result) == 5
