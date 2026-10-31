"""session 의 SessionRepo 기본 클래스: 저장 동작이 없고, jsonl 과 Postgres 저장소가 이를 물려받는지 검증한다."""

import pytest

from jarvis.agent_layer.session.postgres import PostgresSessionRepo
from jarvis.agent_layer.session.session_protocol import SessionRepo
from jarvis.agent_layer.session.jsonl import JsonlSessionRepo

DSN = "postgresql://unused@localhost/none"  # 연결하지 않는다


def test_session_repos_share_base(tmp_path):
    assert isinstance(JsonlSessionRepo(sessions_root=str(tmp_path)), SessionRepo)
    assert isinstance(PostgresSessionRepo(DSN), SessionRepo)


async def test_session_repo_base_has_no_storage():
    repo = SessionRepo()

    with pytest.raises(NotImplementedError):
        await repo.get_messages("s")
    with pytest.raises(NotImplementedError):
        await repo.create("s")
