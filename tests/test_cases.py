import pytest

from inspectors_notebook.case_store import CaseStore
from inspectors_notebook.cases import DWELL_SECONDS, IDLE_SECONDS, PREROLL_SECONDS, CaseManager


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.idle = 0.0

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path):
    return CaseStore(tmp_path / "cases")


@pytest.fixture
def manager(store, clock):
    changes = []
    m = CaseManager(store, lambda: changes.append(1), clock=lambda: clock.t, idle_seconds=lambda: clock.idle, now=lambda: "NOW")
    m.changes = changes
    return m


def visit(url, incident=None, console="defender", **extra):
    return {"type": "event", "kind": "page_visit", "url": url, "title": f"Page {url}", "console": console, "incidentId": incident, **extra}


def query(text, **extra):
    return {"type": "event", "kind": "query", "query": text, "console": "defender", **extra}


def dispositions(manager):
    return [(e.get("url") or e.get("query"), d.disposition, d.reason) for e, d in manager.events()]


def test_manual_start_pause_resume_stop(manager, store, clock):  # FR-1
    case_id = manager.start(incident_id="4821", title="Suspicious PowerShell", entities=["HOST-12", " "], console="defender")
    assert manager.recording
    s = manager.summary()["case"]
    assert (s["incidentId"], s["title"], s["entities"], s["state"]) == ("4821", "Suspicious PowerShell", ["HOST-12"], "recording")

    clock.advance(10)
    manager.pause()
    assert not manager.recording and manager.summary()["case"]["state"] == "paused"
    clock.advance(100)
    manager.ingest(query("ignored while paused"))
    manager.resume()
    clock.advance(5)
    assert manager.summary()["case"]["elapsedSeconds"] == 15
    assert dispositions(manager) == []

    manager.stop()
    assert manager.summary() == {"case": None, "suggestion": None}
    assert store.load(case_id)[0]["title"] == "Suspicious PowerShell"


def test_events_are_stored_with_rule_decisions(manager, store):
    case_id = manager.start(entities=["HOST-12"])
    manager.ingest(visit("https://security.microsoft.com/v2/advanced-hunting"))
    manager.ingest(query("DeviceEvents | where DeviceName == 'HOST-12'"))
    manager.ingest(visit("https://security.microsoft.com/v2/advanced-hunting"))
    manager.ingest(visit("https://security.microsoft.com/incidents", navigationOnly=True))
    assert [d[1:] for d in dispositions(manager)] == [
        ("keep", "console"), ("keep", "entity"), ("hide", "duplicate"), ("hide", "navigation"),
    ]
    assert manager.summary()["case"]["counts"] == {"keep": 2, "review": 0, "hide": 2}
    assert len(store.load(case_id)[1]) == 4


def test_events_while_idle_are_hidden(manager, clock):  # FR-18
    manager.start()
    clock.idle = IDLE_SECONDS + 1
    manager.ingest(query("auto refresh"))
    assert dispositions(manager)[0][1:] == ("hide", "idle")


def test_preroll_joins_the_case_from_the_incident_page_onwards(manager, clock):  # FR-6
    manager.ingest(query("unrelated earlier work"))
    manager.ingest(query("mentions HOST-12 before the incident"))
    manager.ingest(visit("https://security.microsoft.com/incidents/4821", incident="4821"))
    manager.ingest(query("pivot after the incident page"))
    manager.start(incident_id="4821", console="defender", entities=["HOST-12"])
    assert [d[0] for d in dispositions(manager)] == [
        "mentions HOST-12 before the incident",
        "https://security.microsoft.com/incidents/4821",
        "pivot after the incident page",
    ]


def test_preroll_only_keeps_the_last_three_minutes_and_is_used_once(manager, clock):
    manager.ingest(query("HOST-12 too old"))
    clock.advance(PREROLL_SECONDS + 1)
    manager.ingest(query("HOST-12 recent"))
    manager.start(entities=["HOST-12"])
    assert [d[0] for d in dispositions(manager)] == ["HOST-12 recent"]
    manager.stop()
    manager.start(entities=["HOST-12"])
    assert dispositions(manager) == []


def test_start_suggested_after_dwell_then_pivot(manager, clock):  # FR-3
    manager.ingest(visit("https://security.microsoft.com/incidents/4821", incident="4821"))
    clock.advance(DWELL_SECONDS - 1)
    manager.ingest(query("too soon"))
    assert manager.summary()["suggestion"] is None
    manager.ingest(visit("https://security.microsoft.com/incidents/4821", incident="4821"))  # dwell continues
    clock.advance(2)
    manager.ingest(query("DeviceProcessEvents | take 5"))
    assert manager.summary()["suggestion"] == {
        "kind": "start", "console": "defender", "incidentId": "4821",
        "title": "Page https://security.microsoft.com/incidents/4821", "resume": False,
    }
    manager.accept_suggestion()
    assert manager.summary()["case"]["incidentId"] == "4821"
    assert manager.summary()["suggestion"] is None


def test_dismissed_suggestions_stay_dismissed(manager, clock):
    manager.ingest(visit("https://x/incidents/1", incident="1"))
    clock.advance(DWELL_SECONDS)
    manager.ingest(query("pivot"))
    manager.dismiss_suggestion()
    manager.ingest(visit("https://x/incidents/1", incident="1"))
    clock.advance(DWELL_SECONDS)
    manager.ingest(query("pivot again"))
    assert manager.summary()["suggestion"] is None


def test_reopening_a_known_incident_resumes_its_case(manager):  # FR-7
    first = manager.start(incident_id="4821", console="defender", entities=["HOST-12"])
    manager.ingest(query("first session HOST-12"))
    manager.stop()
    again = manager.start(incident_id="4821", console="defender", entities=["203.0.113.7"])
    assert again == first
    assert manager.summary()["case"]["entities"] == ["HOST-12", "203.0.113.7"]
    assert [d[0] for d in dispositions(manager)] == ["first session HOST-12"]


def test_a_different_incident_mid_case_asks_to_switch(manager):  # FR-8
    manager.start(incident_id="4821", console="defender")
    manager.ingest(visit("https://security.microsoft.com/incidents/4821", incident="4821"))
    assert manager.summary()["suggestion"] is None
    manager.ingest(visit("https://security.microsoft.com/incidents/4900", incident="4900"))
    assert manager.summary()["suggestion"]["kind"] == "switch"
    manager.accept_suggestion()
    assert manager.summary()["case"]["incidentId"] == "4900"


def test_adding_an_entity_reruns_the_rules_over_hidden_events(manager, clock):  # FR-21
    manager.start()
    manager.ingest(query("DeviceInfo | where DeviceName == 'HOST-12'"))
    clock.idle = IDLE_SECONDS
    manager.ingest(query("HOST-12 while idle"))
    assert [d[2] for d in dispositions(manager)] == ["console", "idle"]
    manager.add_entity("HOST-12")
    assert [d[2] for d in dispositions(manager)] == ["entity", "entity"]
    manager.remove_entity("HOST-12")
    assert [d[2] for d in dispositions(manager)] == ["console", "idle"]


def test_suggested_entities_come_from_kept_results(manager):
    manager.start()
    manager.ingest({"type": "event", "kind": "result", "rowCount": 1, "entities": [{"type": "ipv4", "value": "203.0.113.7"}]})
    assert manager.summary()["case"]["suggestedEntities"] == ["203.0.113.7"]


def test_keep_hide_and_restore_one_event(manager, store):  # FR-24
    case_id = manager.start()
    manager.ingest(query("noise"))
    manager.set_decision(1, "hide")
    assert dispositions(manager)[0][1:] == ("hide", "analyst")
    manager.set_decision(1, None)
    assert dispositions(manager)[0][1:] == ("keep", "console")
    manager.set_decision(1, "hide")
    assert store.load(case_id)[2] == {1: {"disposition": "hide"}}
    with pytest.raises(ValueError):
        manager.set_decision(1, "delete")


def test_screenshots_are_saved_only_while_recording(manager, store):
    request = {"source": "s", "seq": 3, "ts": "T", "console": "defender", "tabId": 1, "url": "https://x/", "title": "X", "trigger": "navigation"}
    assert manager.add_screenshot(request, b"WEBP", 10, 10) is False
    case_id = manager.start()
    assert manager.add_screenshot(request, b"WEBP", 10, 10) is True
    event = manager.events()[0][0]
    assert (event["kind"], event["file"]) == ("screenshot", "screenshots/000001.webp")
    assert (store.root / case_id / event["file"]).read_bytes() == b"WEBP"


def test_first_tenant_seen_becomes_the_case_tenant(manager):  # FR-14
    manager.start()
    manager.ingest(query("a", tenant="tenant-a"))
    manager.ingest(query("b", tenant="tenant-b"))
    assert manager.summary()["case"]["tenant"] == "tenant-a"
    assert dispositions(manager)[1][1:] == ("review", "other_tenant")


def test_listeners_are_told_about_changes(manager):
    manager.start()
    before = len(manager.changes)
    manager.ingest(query("x"))
    assert len(manager.changes) == before + 1


def test_new_cases_enforce_the_cache(store, clock):  # FR-29 to FR-32
    from inspectors_notebook.settings import Settings

    m = CaseManager(store, clock=lambda: clock.t, settings=lambda: Settings(cache_size=2))
    for i, exported in enumerate([True, False, True]):
        case_id = m.start(incident_id=str(i))
        if exported:
            m.mark_exported()
        m.stop()
        store.update_meta(case_id, lastActivity=f"2026-10-2{i}T10:00:00+01:00")
    newest = m.start(incident_id="9")
    ids = [c["incidentId"] for c in m.cache_state()["cases"]]
    assert "0" not in ids  # oldest and exported: deleted
    assert [c["incidentId"] for c in m.cache_state()["awaitingConfirmation"]] == ["1"]  # never exported: ask first
    unexported = m.cache_state()["awaitingConfirmation"][0]["id"]
    m.keep_case(unexported)
    state = m.cache_state()
    assert state["awaitingConfirmation"] == [] and next(c for c in state["cases"] if c["id"] == unexported)["pinned"]
    m.delete_case(newest)  # the active case is never deleted
    assert any(c["id"] == newest for c in m.cache_state()["cases"])


def test_opening_a_cached_case_resumes_it(manager):
    first = manager.start(title="Manual case")
    manager.ingest(query("kept from the first session"))
    manager.stop()
    manager.start(title="Another")
    manager.open_case(first)
    assert manager.summary()["case"]["id"] == first
    assert [d[0] for d in dispositions(manager)] == ["kept from the first session"]


def test_suggestions_and_dwell_follow_the_settings(store, clock):
    from inspectors_notebook.settings import Settings

    settings = Settings(suggest_cases=False)
    m = CaseManager(store, clock=lambda: clock.t, settings=lambda: settings)
    m.ingest(visit("https://x/incidents/1", incident="1"))
    clock.advance(DWELL_SECONDS)
    m.ingest(query("pivot"))
    assert m.summary()["suggestion"] is None
    settings.suggest_cases, settings.dwell_seconds = True, 5
    m.ingest(visit("https://x/incidents/2", incident="2"))
    clock.advance(5)
    m.ingest(query("pivot"))
    assert m.summary()["suggestion"]["incidentId"] == "2"


def test_resuming_an_untitled_case_takes_the_new_title(manager):
    manager.start(incident_id="4821", console="defender")
    manager.stop()
    manager.start(incident_id="4821", console="defender", title="Driver loads")
    assert manager.summary()["case"]["title"] == "Driver loads"
    manager.stop()
    manager.start(incident_id="4821", console="defender", title="Something else")
    assert manager.summary()["case"]["title"] == "Driver loads"  # an existing title is kept
