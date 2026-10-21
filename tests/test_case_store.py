import pytest

from inspectors_notebook.case_store import CaseStore


@pytest.fixture
def store(tmp_path):
    return CaseStore(tmp_path / "cases")


def meta(case_id, **extra):
    return {"id": case_id, "incidentId": None, "console": None, "lastActivity": "2026-10-21T10:00:00+01:00", **extra}


def test_round_trip(store):
    store.create(meta("c1", incidentId="4821", console="defender"))
    store.append_event("c1", {"id": 1, "kind": "query", "query": "DeviceInfo"})
    store.append_event("c1", {"id": 2, "kind": "result", "rowCount": 0})
    store.append_action("c1", 2, "disposition", "hide")
    store.append_action("c1", 1, "disposition", "keep")
    store.append_action("c1", 1, "disposition", None)  # restored to the rules' decision
    store.append_action("c1", 1, "star", True)
    store.append_action("c1", 1, "annotation", "Download cradle")
    store.append_action("c1", 2, "pin", True)
    store.append_action("c1", 2, "pin", False)
    loaded_meta, events, marks = store.load("c1")
    assert loaded_meta["incidentId"] == "4821"
    assert [e["id"] for e in events] == [1, 2]
    assert marks == {1: {"star": True, "annotation": "Download cradle"}, 2: {"disposition": "hide"}}


def test_a_line_cut_short_by_a_crash_is_skipped(store):
    store.create(meta("c1"))
    store.append_event("c1", {"id": 1})
    with open(store.root / "c1" / "events.jsonl", "a", encoding="utf-8") as f:
        f.write('{"id": 2, "kind": "que')
    assert [e["id"] for e in store.load("c1")[1]] == [1]


def test_screenshots_live_in_the_case(store):
    store.create(meta("c1"))
    name = store.save_screenshot("c1", 7, b"RIFF....WEBP")
    assert name == "screenshots/000007.webp"
    assert (store.root / "c1" / name).read_bytes() == b"RIFF....WEBP"


def test_list_newest_first_and_find_by_incident(store):
    store.create(meta("old", incidentId="1", console="defender", lastActivity="2026-10-20T09:00:00+01:00"))
    store.create(meta("new", incidentId="2", console="defender", lastActivity="2026-10-21T09:00:00+01:00"))
    assert [m["id"] for m in store.list()] == ["new", "old"]
    assert store.find_by_incident("defender", "1") == "old"
    assert store.find_by_incident("sentinel", "1") is None
    assert store.find_by_incident("defender", "3") is None


def test_deleting_a_case_removes_its_files(store):
    store.create(meta("c1"))
    store.append_event("c1", {"id": 1})
    store.save_screenshot("c1", 1, b"x")
    store.delete("c1")
    assert not (store.root / "c1").exists()
    assert store.list() == []


def test_case_ids_cannot_escape_the_store(store):
    for bad in ["../evil", "a/b", "", "c:\\x"]:
        with pytest.raises(ValueError):
            store.load(bad)


def test_a_case_id_is_never_reused(store):
    store.create(meta("c1"))
    with pytest.raises(FileExistsError):
        store.create(meta("c1"))
