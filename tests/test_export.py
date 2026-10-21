"""Exports match golden files in all three formats (S5 exit test), plus the options.

The case is built through the real case manager from the sanitised lab captures, at
fixed times in UTC+1. Regenerate the golden files after an intended change with
    UPDATE_GOLDEN=1 uv run pytest tests/test_export.py
and review the diff before committing.
"""

import json
import os
import zipfile
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from inspectors_notebook import export, timeline
from inspectors_notebook.case_store import CaseStore
from inspectors_notebook.cases import CaseManager

FIXTURES = Path(__file__).parents[1] / "extension" / "tests" / "fixtures"
GOLDEN = Path(__file__).parent / "golden"
TZ = timezone(timedelta(hours=1))
DEFENDER = "https://security.microsoft.com"
TENANT = "00000000-0000-0000-0000-000000000001"


def at(hhmmss):
    return f"2026-10-21T{hhmmss}.000+01:00"


def defender(name, ts_query, ts_result, query_id):
    f = json.loads((FIXTURES / "defender" / f"{name}.json").read_text(encoding="utf-8"))
    common = {"type": "event", "console": "defender", "url": f"{DEFENDER}/v2/advanced-hunting?tid={TENANT}",
              "tenant": TENANT, "source": "s", "tabId": 1, "queryId": query_id}
    query = {**common, "kind": "query", "ts": at(ts_query), "language": "KQL",
             "query": json.loads(f["request"]["body"])["QueryText"]}
    body = json.loads(f["response"]["body"])
    result = {**common, "kind": "result", "ts": at(ts_result), "status": f["response"]["status"]}
    if "Schema" in body:
        columns = [c["Name"] for c in body["Schema"]]
        result.update(columns=columns, rows=[[r[c] for c in columns] for r in body["Results"]], rowCount=len(body["Results"]))
    else:
        result.update(rowCount=None, error=body["ErrorMessage"])
    return query, result


@pytest.fixture
def case(tmp_path):
    store = CaseStore(tmp_path / "cases")
    clock = {"now": at("13:08:34")}
    m = CaseManager(store, now=lambda: clock["now"])
    m.start(incident_id="4821", title="Driver loads on DC01", entities=["dc01.contoso.local"], console="defender")
    m.ingest({"type": "event", "kind": "page_visit", "console": "defender", "ts": at("13:08:40"), "tenant": TENANT,
              "url": f"{DEFENDER}/incidents/4821?tid={TENANT}", "title": "Driver loads on DC01", "incidentId": "4821",
              "recordKind": "incident"})
    for e in defender("rows", "13:09:05", "13:09:06", "q1"):
        m.ingest(e)
    clock["now"] = at("13:10:00")
    m.add_note("Driver loads match Defender platform updates, not attacker activity")
    for e in defender("empty", "13:11:00", "13:11:01", "q2"):
        m.ingest(e)
    for e in defender("error", "13:12:00", "13:12:01", "q3"):
        m.ingest(e)
    m.add_screenshot({"source": "s", "seq": 9, "ts": at("13:13:00"), "console": "defender", "tabId": 1,
                      "url": f"{DEFENDER}/v2/advanced-hunting", "title": "Advanced hunting", "trigger": "results"},
                     b"RIFF\x00\x00\x00\x00WEBPfake", 1280, 720)
    m.ingest({"type": "event", "kind": "page_visit", "console": "defender", "ts": at("13:14:00"), "tenant": TENANT,
              "url": f"{DEFENDER}/alerts?tid={TENANT}", "title": "Alerts", "navigationOnly": True})
    # The analyst's marks: two findings (one annotated), hide the failed query, pin the screenshot.
    m.set_star(2, True)
    m.set_star(5, True)
    m.set_annotation(5, "No file events on DC01 in the last 30 days")
    m.set_decision(7, "hide")
    m.set_decision(8, "hide")
    m.set_pin(9, True)
    items = timeline.build([e for e, _ in m.events()], [d for _, d in m.events()], m.marks())
    return m.case_meta(), items, store.root / m.case_meta()["id"]


@pytest.mark.parametrize("fmt, suffix", [("text", "txt"), ("markdown", "md"), ("html", "html")])
def test_exports_match_golden_files(case, fmt, suffix):
    meta, items, _ = case
    out = export.render(meta, items, export.Options(fmt=fmt, tz=TZ))
    golden = GOLDEN / f"case-4821.{suffix}"
    if os.environ.get("UPDATE_GOLDEN"):
        golden.parent.mkdir(exist_ok=True)
        golden.write_text(out, encoding="utf-8", newline="\n")
    assert out == golden.read_text(encoding="utf-8")


def test_hidden_events_only_when_asked(case):
    meta, items, _ = case
    plain = export.render(meta, items, export.Options(tz=TZ))
    assert "Failed:" not in plain and "PAGE" not in plain
    everything = export.render(meta, items, export.Options(tz=TZ, hidden=True))
    assert "DeviceFileEven" in everything and "Failed: 'take' operator" in everything
    assert "13:14  PAGE     Alerts" in everything


def test_include_options(case):
    meta, items, _ = case
    no_notes = export.render(meta, items, export.Options(tz=TZ, notes=False))
    assert "NOTE" not in no_notes
    no_rows = export.render(meta, items, export.Options(tz=TZ, rows=False))
    assert "PktMon.sys" not in no_rows and "Result: 4 rows" in no_rows
    two_rows = export.render(meta, items, export.Options(tz=TZ, row_limit=2))
    assert two_rows.count("dc01.contoso.local  system  DriverLoad") == 2
    no_findings = export.render(meta, items, export.Options(tz=TZ, findings=False))
    assert "KEY FINDINGS" not in no_findings
    no_shots = export.render(meta, items, export.Options(tz=TZ, screenshots=False))
    assert "[screenshot" not in no_shots


def test_utc_shown_alongside_when_asked(case):
    meta, items, _ = case
    out = export.render(meta, items, export.Options(tz=TZ, utc=True))
    assert "Case started 21/10/2026 13:08 (12:08 UTC)" in out
    assert "13:09 (12:09 UTC)  QUERY" in out
    assert "21:05 to 21:08 (20:05 to 20:08 UTC)" in out


def test_html_escapes_console_content(tmp_path):
    m = CaseManager(CaseStore(tmp_path / "cases"), now=lambda: at("10:00:00"))
    m.start(title="<b>title</b>")
    m.add_note('<script>alert("x")</script> & more')
    items = timeline.build([e for e, _ in m.events()], [d for _, d in m.events()], m.marks())
    out = export.render(m.case_meta(), items, export.Options(fmt="html", tz=TZ))
    assert "<script>" not in out and "&lt;script&gt;" in out and "&lt;b&gt;title&lt;/b&gt;" in out


def test_screenshots_zip_uses_timeline_names(case, tmp_path):
    meta, items, case_dir = case
    files = export.screenshot_files(case_dir, items, TZ)
    assert [name for name, _ in files] == ["1313-0009-results.webp"]
    assert export.write_zip(tmp_path / "shots.zip", files) == 1
    with zipfile.ZipFile(tmp_path / "shots.zip") as z:
        assert z.namelist() == ["1313-0009-results.webp"]
        assert z.read("1313-0009-results.webp").startswith(b"RIFF")
    text = export.render(meta, items, export.Options(tz=TZ))
    assert "[screenshot 1313-0009-results.webp]" in text
