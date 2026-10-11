"""[core] AnyTrigger.wait 가 취소돼도 하위 트리거 작업을 남기지 않는다."""

import asyncio

import pytest

from jarvis.core.proactive.triggers import AnyTrigger, ReflectionTrigger


class NeverFires(ReflectionTrigger):
    def __init__(self) -> None:
        self.cancelled = False

    async def wait(self) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.mark.asyncio
async def test_cancelling_wait_cancels_children():
    children = [NeverFires(), NeverFires()]
    waiter = asyncio.ensure_future(AnyTrigger(list(children)).wait())
    await asyncio.sleep(0.01)

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    assert all(c.cancelled for c in children)
