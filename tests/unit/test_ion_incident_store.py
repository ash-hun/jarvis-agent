"""ion 의 사고 저장소: 같은 id 는 하나, 알림과 답은 처음 것만 남고, 파일로 돌아온다."""

from jarvis.ion.incident_store import Incident, IncidentStore


def _incident(i: str = "backend_down:backend:1") -> Incident:
    return Incident(id=i, kind="backend_down", target="backend", detail="x", opened_ms=10)


def test_open_twice_keeps_one_and_survives_reload(tmp_path):
    store = IncidentStore(tmp_path / "ion" / "incidents.json")
    first, created = store.open(_incident())
    again, created_again = store.open(_incident())

    assert created and not created_again and first == again
    assert IncidentStore(tmp_path / "ion" / "incidents.json").open_incidents() == [first]


def test_notify_respond_close_keep_first_values_and_unknown_id_is_none(tmp_path):
    store = IncidentStore(tmp_path / "incidents.json")
    store.open(_incident())

    assert store.mark_notified("backend_down:backend:1", 20).notified_ms == 20
    assert store.mark_notified("backend_down:backend:1", 30).notified_ms == 20
    assert store.respond("backend_down:backend:1", "restart", 40).response == "restart"
    assert store.respond("backend_down:backend:1", "ignore", 50).response == "restart"
    assert store.close("backend_down:backend:1", 60).open is False
    assert store.open_incidents() == [] and store.respond("ghost", "restart", 1) is None


def test_recent_lists_open_and_closed_newest_first_within_the_limit(tmp_path):
    store = IncidentStore(tmp_path / "incidents.json")
    for i, opened in (("a", 10), ("b", 30), ("c", 20)):
        store.open(Incident(id=i, kind="backend_down", target="backend", detail="x", opened_ms=opened))
    store.close("b", 40)

    assert [i.id for i in store.recent(2)] == ["b", "c"]
    assert [i.id for i in store.recent(10)] == ["b", "c", "a"] and store.recent(0) == []
