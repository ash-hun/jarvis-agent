"""procedures 기능의 옛 세대 파일 수렴 계획: 승인된 것을 남기고 늦은 초안은 개정으로, 다 고친 저장소는 그대로."""

from jarvis.core.procedures.procedures_store import STATUS_APPROVED, Procedure
from jarvis.core.procedures.converge import plan_convergence


def _p(name: str, source: str, status: str = "draft") -> Procedure:
    return Procedure(name=name, description="d", body=f"{name}\n", status=status, source=source)


def test_plan_keeps_approved_and_attaches_newer_draft_as_revision():
    procs = [_p("a", "edm:k:t:1", STATUS_APPROVED), _p("a-2", "edm:k:t:2"), _p("a-3", "edm:k:t:3")]

    [plan] = plan_convergence(procs)

    assert (plan.keep.name, plan.keep.source, plan.keep.generation) == ("a", "edm:k:t", 1)
    assert plan.keep.revision is not None and plan.keep.revision.body == "a-3\n"
    assert plan.archive == ("a-2", "a-3")


def test_plan_without_legacy_sources_is_empty():
    assert plan_convergence([_p("a", "edm:k:t"), _p("b", "s1#0")]) == []
    [plan] = plan_convergence([_p("a", "edm:k:t:1"), _p("b", "edm:k:t:2")])
    assert (plan.keep.name, plan.keep.revision, plan.archive) == ("b", None, ("a",))
