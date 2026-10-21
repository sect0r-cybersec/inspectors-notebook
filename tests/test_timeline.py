from datetime import timedelta, timezone

from inspectors_notebook import timeline
from inspectors_notebook.rules import Decision

TZ = timezone(timedelta(hours=1))


def ev(i, kind, **extra):
    return {"id": i, "kind": kind, "source": "s", "tabId": 1, **extra}


def test_console_times_with_seven_decimals_are_read():
    assert timeline.clock("2026-10-11T20:05:28.8709245Z", TZ) == "21:05"
    assert timeline.clock("2026-10-21T13:08:34.480+01:00", TZ, utc=True) == "13:08 (12:08 UTC)"
    assert timeline.clock("not a time") == ""


def test_a_query_and_its_result_are_one_item_with_the_strongest_decision():
    events = [ev(1, "query", queryId="q", query="DeviceInfo"), ev(2, "result", queryId="q", rowCount=1, rows=[["HOST-12"]], columns=["DeviceName"])]
    decisions = [Decision("hide", "duplicate"), Decision("keep", "entity")]
    [item] = timeline.build(events, decisions, {})
    assert (item.ids, item.kind, item.disposition, item.reason) == ([1, 2], "query", "keep", "entity")


def test_the_analysts_decision_wins_on_a_merged_item():
    events = [ev(1, "query", queryId="q"), ev(2, "result", queryId="q", rowCount=0)]
    [item] = timeline.build(events, [Decision("hide", "analyst"), Decision("keep", "negative_finding")], {})
    assert (item.disposition, item.reason) == ("hide", "analyst")


def test_results_from_another_tab_or_without_a_query_stand_alone():
    events = [ev(1, "query", queryId="q"), {**ev(2, "result", queryId="q", rowCount=3), "tabId": 2}]
    items = timeline.build(events, [Decision("keep", "console")] * 2, {})
    assert [i.kind for i in items] == ["query", "result"]


def test_marks_come_from_the_first_event_of_an_item():
    events = [ev(1, "note", text="x"), ev(2, "screenshot", file="screenshots/000002.webp", trigger="navigation")]
    items = timeline.build(events, [Decision("keep", "console")] * 2, {1: {"star": True, "annotation": "why"}, 2: {"pin": True}})
    assert (items[0].star, items[0].annotation, items[1].pinned) == (True, "why", True)


def test_summary_lines_never_invent_anything():
    assert timeline.summary_line({"rowCount": 0}, []) == "No results"
    assert timeline.summary_line({"rowCount": None}, []) == "Results not read"
    assert timeline.summary_line({"error": "bad table"}, []) == "Failed: bad table"
    capped = {"rowCount": 7000, "columns": ["DeviceName"], "rows": [["a"]], "truncated": True}
    assert timeline.summary_line(capped, []) == "7000 rows; rows capped in this capture"


def test_record_pages_are_labelled_by_kind():
    [item] = timeline.build([ev(1, "page_visit", incidentId="77", recordKind="case", title="Phish")], [Decision("keep", "console")], {})
    assert (item.kind, item.label, item.text) == ("record", "Case 77", "Phish")


def test_counts_include_findings():
    items = timeline.build([ev(1, "note", text="a"), ev(2, "note", text="b")], [Decision("keep", "console"), Decision("hide", "idle")], {1: {"star": True}})
    assert timeline.counts(items) == {"keep": 1, "review": 0, "hide": 1, "findings": 1}
