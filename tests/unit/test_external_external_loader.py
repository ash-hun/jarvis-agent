"""external 기능의 소스 로더: YAML 을 소스 명세로 읽고 잘못된 항목과 파일을 격리하는지 검증한다."""

from jarvis.core.external import load_source_specs


def test_load_source_specs_returns_empty_when_dir_missing(tmp_path) -> None:
    assert load_source_specs(str(tmp_path / "nope")) == []


def test_load_source_specs_parses_list_and_skips_invalid_items(tmp_path) -> None:
    (tmp_path / "sources.yaml").write_text(
        "- name: cal\n"
        "  server: gcal\n"
        "  tool: list_events\n"
        "  args: {time_min: now}\n"
        "  interval_sec: 60\n"
        "- name: broken\n",
        encoding="utf-8",
    )

    specs = load_source_specs(str(tmp_path))

    assert [s.name for s in specs] == ["cal"]
    assert specs[0].args == {"time_min": "now"}
    assert specs[0].interval_sec == 60


def test_load_source_specs_isolates_unparsable_file(tmp_path) -> None:
    (tmp_path / "a.yaml").write_text("name: [unclosed\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("name: mail\nserver: gmail\ntool: search\n", encoding="utf-8")

    specs = load_source_specs(str(tmp_path))

    assert [s.name for s in specs] == ["mail"]
