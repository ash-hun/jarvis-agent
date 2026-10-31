"""usermodel: /usermodel 명령이 모델이 없음을 알리고 build 로 증류해 저장한 뒤 보여 주는지 검증."""

import json

from jarvis.agent_layer.usermodel import InMemoryUserModelStore, UserModelBuilder
from jarvis.core.slash.usermodel_cmd import make_usermodel_handler
from jarvis.memory import MemoryItem, MemoryKind, MemoryScope

MODEL_JSON = json.dumps({"summary": "간결·직접적 답 선호", "traits": ["Python", "테스트 우선"]}, ensure_ascii=False)


class FakeLTM:
    def __init__(self, contents):
        self.contents = contents

    async def recent(self, scope, limit=10):
        return [MemoryItem(content=c, kind=MemoryKind.SEMANTIC, scope=scope, source="x") for c in self.contents[:limit]]


async def test_usermodel_command_builds_saves_and_shows(faux_model_with_response):
    scope = MemoryScope(user_id="local")
    store = InMemoryUserModelStore()
    builder = UserModelBuilder(model=faux_model_with_response(response=MODEL_JSON))
    handler = make_usermodel_handler(store, builder, FakeLTM(["요약 A", "요약 B"]))

    assert "아직 모델이 없습니다" in await handler("", scope)
    assert "간결·직접적" in await handler("build", scope)
    assert (await store.get()).summary == "간결·직접적 답 선호"
    assert "간결·직접적" in await handler("", scope)
