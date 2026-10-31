"""[agent_layer] JsonlSessionRepo.create_branch() 로 대화를 갈라 내는 동작 테스트."""

from jarvis.model_layer.model_types import UserMessage


class TestSessionMetadataParentId:
    def test_metadata_has_parent_id_field(self):
        from jarvis.agent_layer.session.session_protocol import SessionMetadata

        meta = SessionMetadata(
            session_id="abc",
            cwd=".",
            created_at=0,
            updated_at=0,
            message_count=0,
        )
        assert meta.parent_id is None

    def test_metadata_parent_id_set(self):
        from jarvis.agent_layer.session.session_protocol import SessionMetadata

        meta = SessionMetadata(
            session_id="child",
            cwd=".",
            created_at=0,
            updated_at=0,
            message_count=0,
            parent_id="parent",
        )
        assert meta.parent_id == "parent"


class TestJsonlSessionRepoIdempotentCreate:
    async def test_create_idempotent(self, jsonl_repo):
        await jsonl_repo.create(session_id="sess-1", cwd="/tmp")
        # Append a message to increase message_count
        msg = UserMessage(content="hello")
        await jsonl_repo.append("sess-1", msg)

        meta2 = await jsonl_repo.create(session_id="sess-1", cwd="/tmp")
        # Should return existing meta: message_count must NOT reset to 0
        assert meta2.session_id == "sess-1"
        assert meta2.message_count > 0, "create() must be idempotent: must not reset message_count"

    async def test_create_new_session(self, jsonl_repo):
        meta = await jsonl_repo.create(session_id="brand-new")
        assert meta.session_id == "brand-new"
        assert meta.message_count == 0


class TestJsonlSessionRepoBranch:
    async def test_create_branch_copies_messages(self, jsonl_repo):
        await jsonl_repo.create(session_id="parent-sess")
        msg1 = UserMessage(content="First message")
        msg2 = UserMessage(content="Second message")
        await jsonl_repo.append("parent-sess", msg1)
        await jsonl_repo.append("parent-sess", msg2)

        branch_meta = await jsonl_repo.create_branch("parent-sess")

        assert branch_meta.parent_id == "parent-sess"
        assert branch_meta.session_id != "parent-sess"
        assert branch_meta.message_count == 2

        branch_messages = await jsonl_repo.get_messages(branch_meta.session_id)
        assert len(branch_messages) == 2
        assert branch_messages[0].content == "First message"
        assert branch_messages[1].content == "Second message"

    async def test_create_branch_of_empty_session(self, jsonl_repo):
        await jsonl_repo.create(session_id="empty-parent")
        branch_meta = await jsonl_repo.create_branch("empty-parent")

        assert branch_meta.parent_id == "empty-parent"
        assert branch_meta.message_count == 0

    async def test_branch_metadata_in_list(self, jsonl_repo):
        await jsonl_repo.create(session_id="root-session")
        await jsonl_repo.append("root-session", UserMessage(content="hi"))
        branch = await jsonl_repo.create_branch("root-session")

        sessions = await jsonl_repo.list()
        ids = [s.session_id for s in sessions]
        assert "root-session" in ids
        assert branch.session_id in ids

        branch_in_list = next(s for s in sessions if s.session_id == branch.session_id)
        assert branch_in_list.parent_id == "root-session"

    async def test_branch_has_unique_id(self, jsonl_repo):
        await jsonl_repo.create(session_id="src-sess")
        b1 = await jsonl_repo.create_branch("src-sess")
        b2 = await jsonl_repo.create_branch("src-sess")
        assert b1.session_id != b2.session_id
        assert b1.parent_id == b2.parent_id == "src-sess"


class TestSidebarTreeView:
    def test_root_sessions_shown_without_prefix(self):
        """parent_id=None 인 세션은 ↳ 없이 표시되어야 한다."""
        from jarvis.agent_layer.session.session_protocol import SessionMetadata

        root = SessionMetadata(
            session_id="root-abc123456789",
            cwd=".",
            created_at=0,
            updated_at=0,
            message_count=3,
        )
        short_id = root.session_id[:14]
        label = f"{short_id} ({root.message_count})"
        assert "↳" not in label
        assert "root-abc12345" in label

    def test_child_session_shown_with_prefix(self):
        """parent_id 있는 세션은 ↳ 접두사로 표시되어야 한다."""
        from jarvis.agent_layer.session.session_protocol import SessionMetadata

        child = SessionMetadata(
            session_id="child-xyz987654321",
            cwd=".",
            created_at=0,
            updated_at=0,
            message_count=1,
            parent_id="root-abc123456789",
        )
        short_id = child.session_id[:12]
        label = f"↳ {short_id} ({child.message_count})"
        assert label.startswith("↳")


# ── 세션의 에이전트 ─────────────────────────────────────────────────────────────


async def test_jsonl_session_agent_is_fixed_at_creation(tmp_path):
    from jarvis.agent_layer.session.jsonl import JsonlSessionRepo

    repo = JsonlSessionRepo(str(tmp_path))
    assert await repo.get_meta("k1") is None
    created = await repo.create(session_id="k1", agent_id="karen")
    again = await repo.create(session_id="k1", agent_id="main")
    assert created.agent_id == again.agent_id == "karen"
    assert (await repo.get_meta("k1")).agent_id == "karen"
    branch = await repo.create_branch("k1")
    assert branch.agent_id == "karen"


async def test_jsonl_old_meta_without_agent_reads_as_main(tmp_path):
    import json

    from jarvis.agent_layer.session.jsonl import JsonlSessionRepo

    (tmp_path / "old.meta.json").write_text(json.dumps(
        {"session_id": "old", "cwd": ".", "created_at": 1, "updated_at": 1, "message_count": 0}
    ))
    assert (await JsonlSessionRepo(str(tmp_path)).get_meta("old")).agent_id == "main"
