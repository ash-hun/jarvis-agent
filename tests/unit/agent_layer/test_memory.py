"""[agent_layer] 메모리 미들웨어 체인 테스트."""

from jarvis.agent_layer.memory.chain import MemoryMiddlewareChain
from jarvis.model_layer.types import UserMessage


def _make_messages(n: int) -> list:
    return [UserMessage(content=f"msg {i}") for i in range(n)]


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
