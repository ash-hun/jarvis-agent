"""procedures 기능의 절차 저장소: 파일 왕복과 upsert, 상태 변경과 개정 승인의 멱등성, 보관, 깨진 파일 건너뛰기."""

import pytest
from dataclasses import replace

from jarvis.core.procedures import (
    STATUS_APPROVED,
    STATUS_DRAFT,
    Procedure,
    ProcedureStore,
    build_procedure,
    find_spans,
    parse_draft,
)
from tests.fixtures.procedures_helpers import PLAN_JSON, success_history


def test_save_twice_keeps_one_file_and_roundtrips(tmp_path):
    store = ProcedureStore(str(tmp_path / "procs"))
    proc = Procedure(
        name="deploy", description="배포", body="절차:\n1. {{args}} 배포\n", source="s1#0", tools=("bash",)
    )

    store.save(proc)
    store.save(proc)

    assert [p.name for p in store.list()] == ["deploy"]
    loaded = store.get("deploy")
    assert loaded == proc
    assert loaded.render("staging") == "절차:\n1. staging 배포\n"
    assert store.has_source("s1#0") and not store.has_source("s1#9")


def test_save_roundtrips_learned_plan(tmp_path):
    store = ProcedureStore(str(tmp_path))
    proc = build_procedure(parse_draft(PLAN_JSON), find_spans(success_history())[0], "s1#0", "run-tests")

    store.save(proc)

    assert store.get("run-tests") == proc


def test_set_status_is_idempotent_and_delete_reports_presence(tmp_path):
    store = ProcedureStore(str(tmp_path))
    store.save(Procedure(name="x", description="d", body="b"))

    assert store.set_status("x", STATUS_APPROVED).approved
    mtime = (tmp_path / "x.md").stat().st_mtime_ns
    assert store.set_status("x", STATUS_APPROVED).approved
    assert (tmp_path / "x.md").stat().st_mtime_ns == mtime
    assert store.set_status("nope", STATUS_DRAFT) is None
    with pytest.raises(ValueError):
        store.set_status("x", "weird")
    assert store.delete("x") is True
    assert store.delete("x") is False


def test_list_skips_unparseable_file(tmp_path):
    (tmp_path / "ok.md").write_text("---\nname: ok\ndescription: d\n---\nbody\n")
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe")

    assert [p.name for p in ProcedureStore(str(tmp_path)).list()] == ["ok"]


def test_approve_adopts_revision_keeping_name_and_drop_revision_marks_generation(tmp_path):
    store = ProcedureStore(str(tmp_path))
    revision = Procedure(name="x", description="새", body="새 본문\n", generation=2)
    store.save(Procedure(name="x", description="옛", body="옛 본문\n", status=STATUS_APPROVED, source="edm:a:t",
                         generation=1, revision=revision))
    assert store.get("x").revision == revision

    approved = store.approve("x")
    assert (approved.body, approved.source, approved.generation, approved.revision) == ("새 본문\n", "edm:a:t", 2, None)
    assert store.approve("x") == approved and store.approve("nope") is None

    store.save(replace(approved, revision=replace(revision, generation=3)))
    assert store.drop_revision("x").generation == 3 and store.get("x").body == "새 본문\n"
    assert store.drop_revision("x") is None


def test_archive_moves_file_out_of_list_without_overwriting(tmp_path):
    store = ProcedureStore(str(tmp_path))
    for _ in range(2):
        store.save(Procedure(name="x", description="d", body="b\n"))
        store.archive("x")

    assert store.list() == [] and store.archive("x") is None
    assert sorted(p.name for p in (tmp_path / ".archive").iterdir()) == ["x.1.md", "x.md"]
