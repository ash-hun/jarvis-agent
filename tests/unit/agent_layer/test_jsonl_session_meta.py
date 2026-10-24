"""JsonlSessionRepo: 같은 세션을 동시에 만들고 읽어도 쓰다 만 메타 파일을 읽지 않는다."""

import asyncio

from jarvis.agent_layer.session.jsonl import JsonlSessionRepo


def test_concurrent_create_and_read_never_sees_a_half_written_meta(tmp_path):
    repo = JsonlSessionRepo(str(tmp_path))

    async def race(sid: str) -> None:
        # 화면 둘이 아직 없는 세션에 동시에 붙는다. 한쪽이 쓰는 동안 다른 쪽이 읽는다
        await asyncio.gather(repo.create(sid), repo.get_meta(sid), repo.create(sid), repo.get_meta(sid))

    async def main() -> None:
        for i in range(200):
            await race(f"s{i}")

    asyncio.run(main())
    assert len(list(tmp_path.glob("*.meta.json"))) == 200
    assert list(tmp_path.glob("*.tmp")) == []
