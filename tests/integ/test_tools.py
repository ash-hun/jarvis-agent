"""tools 기능: GET /api/tools 가 도구 목록에 승인 필요 여부를 표시함을 검증한다."""

import pytest

pytest.importorskip("fastapi")

from tests.fixtures.web_hud_helpers import web_assembly, web_client  # noqa: E402


def test_tools_list_marks_approval_required(monkeypatch, tmp_path):
    with web_client(web_assembly(monkeypatch, tmp_path)) as client:
        tools = {t["name"]: t for t in client.get("/api/tools").json()["tools"]}

    assert tools["bash"]["approval"] is True
    assert tools["read_file"]["approval"] is False
