"""S4 exit test: a scripted investigation produces the expected timeline.

Events are built from the sanitised purple team lab captures in extension/tests/fixtures,
shaped as the extension sends them. Incident pages carry an incident ID directly, as
they will once the console's incident URL patterns are known.
"""

import json
from pathlib import Path

import pytest

from inspectors_notebook.case_store import CaseStore
from inspectors_notebook.cases import DWELL_SECONDS, IDLE_SECONDS, CaseManager

FIXTURES = Path(__file__).parents[1] / "extension" / "tests" / "fixtures"
DEFENDER = "https://security.microsoft.com"
TENANT = "00000000-0000-0000-0000-000000000001"
OTHER_TENANT = "00000000-0000-0000-0000-0000000000ff"


def fixture(console, name):
    return json.loads((FIXTURES / console / f"{name}.json").read_text(encoding="utf-8"))


def defender_query(name, tenant=TENANT):
    f = fixture("defender", name)
    query = {"type": "event", "kind": "query", "console": "defender", "url": f"{DEFENDER}/v2/advanced-hunting?tid={tenant}",
             "tenant": tenant, "query": json.loads(f["request"]["body"])["QueryText"]}
    body = json.loads(f["response"]["body"])
    result = {**query, "kind": "result", "status": f["response"]["status"], "query": None}
    if "Schema" in body:
        columns = [c["Name"] for c in body["Schema"]]
        result.update(columns=columns, rows=[[r[c] for c in columns] for r in body["Results"]], rowCount=len(body["Results"]))
    else:
        result.update(rowCount=None, error=body["ErrorMessage"])
    return query, result


def visit(path, tenant=TENANT, **extra):
    return {"type": "event", "kind": "page_visit", "console": "defender", "url": f"{DEFENDER}{path}?tid={tenant}",
            "title": "Microsoft Defender", "tenant": tenant, **extra}


class Clock:
    t = 0.0
    idle = 0.0


@pytest.fixture
def setup(tmp_path):
    clock = Clock()
    store = CaseStore(tmp_path / "cases")
    manager = CaseManager(store, clock=lambda: clock.t, idle_seconds=lambda: clock.idle, now=lambda: "NOW")
    return manager, store, clock


def timeline(manager):
    rows = []
    for event, decision in manager.events():
        label = event.get("query") or event.get("error") or event["url"].split("?")[0].removeprefix(DEFENDER)
        if event["kind"] == "result" and not event.get("error"):
            label = f"{event['rowCount']} rows"
        rows.append((event["kind"], label.replace("\r\n", " "), decision.disposition, decision.reason))
    return rows


EXPECTED = [
    ("page_visit", "/incidents/4821", "keep", "console"),
    ("query", "DeviceEvents | take 10", "keep", "console"),
    ("result", "4 rows", "keep", "entity"),
    ("query", "DeviceFileEvents | take 10", "keep", "console"),
    ("result", "0 rows", "keep", "negative_finding"),
    ("query", "DeviceEvents | take 10", "hide", "duplicate"),
    ("result", "4 rows", "keep", "entity"),
    ("query", "DeviceFileEven | take 10", "keep", "console"),
    ("result", "'take' operator: Failed to resolve table or column expression named 'DeviceFileEven'", "hide", "analyst"),
    ("query", "DeviceFileEvents | take 10", "review", "other_tenant"),
    ("page_visit", "/v2/advanced-hunting", "hide", "idle"),
    ("page_visit", "/alerts", "hide", "navigation"),
]


def test_scripted_lab_investigation(setup):
    manager, store, clock = setup
    rows_q, rows_r = defender_query("rows")
    empty_q, empty_r = defender_query("empty")
    error_q, error_r = defender_query("error")

    # Before a case: the incident list, then the incident, then a pivot query.
    manager.ingest(visit("/incidents", navigationOnly=True))
    clock.t += 1
    manager.ingest(visit("/incidents/4821", incidentId="4821", title="Driver loads on DC01"))
    clock.t += DWELL_SECONDS + 5
    manager.ingest(rows_q)
    suggestion = manager.summary()["suggestion"]
    assert (suggestion["kind"], suggestion["incidentId"], suggestion["title"]) == ("start", "4821", "Driver loads on DC01")

    # The analyst accepts; the incident page and the pivot join from the pre-roll.
    manager.accept_suggestion()
    case = manager.summary()["case"]
    assert (case["incidentId"], case["tenant"]) == ("4821", TENANT)

    manager.ingest(rows_r)
    manager.add_entity("dc01.contoso.local")  # spotted in the results: re-runs the rules
    manager.ingest(empty_q)
    manager.ingest(empty_r)
    manager.ingest(rows_q)  # the same query again
    manager.ingest(rows_r)
    manager.ingest(error_q)
    manager.ingest(error_r)
    manager.set_decision(9, "hide")  # the analyst hides the failed query's error
    manager.ingest(defender_query("empty", tenant=OTHER_TENANT)[0])
    clock.idle = IDLE_SECONDS + 60
    manager.ingest(visit("/v2/advanced-hunting"))  # an auto-refresh while away
    clock.idle = 0
    manager.ingest(visit("/alerts", navigationOnly=True))

    assert timeline(manager) == EXPECTED
    assert manager.summary()["case"]["counts"] == {"keep": 7, "review": 1, "hide": 4}

    # The case on disk reproduces the same timeline when the incident is reopened (FR-7).
    manager.stop()
    manager.start(incident_id="4821", console="defender")
    assert timeline(manager) == EXPECTED

    # Deleting the case removes its files (docs/decisions.md: no encrypted store).
    case_id = manager.summary()["case"]["id"]
    manager.stop()
    store.delete(case_id)
    assert not (store.root / case_id).exists()
