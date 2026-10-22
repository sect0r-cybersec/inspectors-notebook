import csv
import json

import pytest

from inspectors_notebook import evaluation
from inspectors_notebook.case_store import CaseStore
from inspectors_notebook.cases import CaseManager
from inspectors_notebook.rules import HIDE, KEEP, REVIEW


@pytest.fixture
def store(tmp_path):
    return CaseStore(tmp_path / "cases")


@pytest.fixture
def case(store):
    """A small lab-style case: an entity query with its result, an unrelated query, a page, a note."""
    m = CaseManager(store, now=lambda: "2026-10-22T09:00:00.000+01:00")
    case_id = m.start(incident_id="4821", title="Suspicious PowerShell", entities=["HOST-12"], console="defender")
    base = {"type": "event", "source": "s", "tabId": 1, "console": "defender"}
    m.ingest({**base, "kind": "query", "seq": 1, "ts": "2026-10-22T09:01:00.000+01:00", "queryId": "q1",
              "query": "DeviceProcessEvents | where DeviceName == 'HOST-12'"})
    m.ingest({**base, "kind": "result", "seq": 2, "queryId": "q1", "rowCount": 1, "columns": ["DeviceName", "ProcessCommandLine"],
              "rows": [["HOST-12", "=cmd|' /c calc'!A1"]]})
    m.ingest({**base, "kind": "query", "seq": 3, "ts": "2026-10-22T09:02:00.000+01:00", "queryId": "q2",
              "query": "DeviceInfo | summarize count() by OSPlatform"})
    m.ingest({**base, "kind": "page_visit", "seq": 4, "ts": "2026-10-22T09:03:00.000+01:00",
              "url": "https://www.virustotal.com/gui/file/abc", "title": "a.exe"})
    m.add_note("Encoded PowerShell on HOST-12")
    m.set_decision(3, HIDE)  # the analyst hid the unrelated query in the panel
    m.set_star(1, True)
    m.stop()
    return case_id


def read_sheet(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_sheet(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        out = csv.DictWriter(f, evaluation.COLUMNS)
        out.writeheader()
        out.writerows(rows)


def test_the_sheet_has_one_row_per_item_prefilled_from_the_panel(store, case, tmp_path):
    sheet = tmp_path / "sheet.csv"
    assert evaluation.export_sheet(store, case, sheet) == 3  # the note is the analyst's own, so not labelled
    rows = read_sheet(sheet)
    assert [(r["kind"], r["entity_match"], r["relevant"], r["notable"]) for r in rows] == [
        ("query", "y", "", "y"),  # starred
        ("query", "n", "n", ""),  # hidden in the panel
        ("page", "n", "", ""),
    ]
    # The rules column ignores the analyst's Hide, so the baseline is not scored on the answers.
    assert rows[1]["rules"] == KEEP


def test_cells_that_would_run_as_formulas_are_escaped(store, case, tmp_path):
    sheet = tmp_path / "sheet.csv"
    evaluation.export_sheet(store, case, sheet)
    text = read_sheet(sheet)[0]["event"]
    assert "ProcessCommandLine==cmd" in text  # inside the text, harmless
    assert evaluation._cell("=cmd|' /c calc'!A1") == "'=cmd|' /c calc'!A1"
    assert evaluation._cell("@SUM(1)") == "'@SUM(1)"
    assert evaluation._cell("HOST-12") == "HOST-12"


def test_build_keeps_labelled_rows_with_the_models_input(store, case, tmp_path):
    sheet = tmp_path / "sheet.csv"
    evaluation.export_sheet(store, case, sheet)
    rows = read_sheet(sheet)
    rows[0]["relevant"], rows[2]["relevant"], rows[2]["notable"] = "y", "Yes", "n"
    write_sheet(sheet, rows)

    lines = evaluation.build(store, [sheet])
    assert [(line["kind"], line["relevant"], line["notable"]) for line in lines] == [
        ("query", True, True), ("query", False, None), ("page", True, False),
    ]
    first = lines[0]
    assert first["state"].startswith("Case: Suspicious PowerShell (incident 4821). Entities: HOST-12.\nEvent: Hunting query (Defender):")
    assert "Result: 1 row." in first["state"] and first["entity_match"] is True
    assert json.loads(json.dumps(first)) == first


def test_unlabelled_rows_are_left_out_and_bad_answers_are_refused(store, case, tmp_path):
    sheet = tmp_path / "sheet.csv"
    evaluation.export_sheet(store, case, sheet)
    rows = read_sheet(sheet)
    assert len(evaluation.build(store, [sheet])) == 1  # only the hidden row has an answer
    rows[0]["relevant"] = "maybe"
    write_sheet(sheet, rows)
    with pytest.raises(ValueError, match="relevant must be y or n"):
        evaluation.build(store, [sheet])


def test_the_model_never_overrides_an_entity_match_and_borderline_goes_to_review():
    assert evaluation.model_decision(True, 0.0) == KEEP  # FR-19
    assert [evaluation.model_decision(False, s) for s in (0.1, 0.3, 0.5, 0.7, 0.9)] == [HIDE, HIDE, REVIEW, KEEP, KEEP]


def test_scoring_compares_each_system_against_entity_matching():
    evalset = [
        {"key": "c:1", "relevant": True, "entity_match": True, "rules": KEEP},
        {"key": "c:2", "relevant": True, "entity_match": False, "rules": KEEP},
        {"key": "c:3", "relevant": False, "entity_match": False, "rules": KEEP},
        {"key": "c:4", "relevant": False, "entity_match": False, "rules": HIDE},
    ]
    good = {"c:1": {"relevant": 0.1}, "c:2": {"relevant": 0.9}, "c:3": {"relevant": 0.2}, "c:4": {"relevant": 0.1}}
    unsure = {"c:1": {"relevant": 0.5}, "c:2": {"relevant": 0.5}, "c:3": {"relevant": 0.5}, "c:4": {"relevant": 0.5}}
    bad = {"c:1": {"relevant": 0.9}, "c:2": {"relevant": 0.1}, "c:3": {"relevant": 0.9}, "c:4": {"relevant": 0.9}}
    result = evaluation.score(evalset, {"good": good, "bad": bad, "unsure": unsure})

    entity = result["entity matching"]
    assert (entity["kept"], entity["hidden"], entity["evidence_lost"], entity["recall"]) == (1, 3, 1, 0.5)
    assert result["rules"]["noise_kept"] == 1
    assert (result["good"]["evidence_lost"], result["good"]["review"], result["good"]["gate2"]) == (0, 0, True)
    # Sending everything uncertain to review loses nothing but saves the analyst nothing either.
    assert (result["unsure"]["evidence_lost"], result["unsure"]["review_share"], result["unsure"]["gate2"]) == (0, 0.75, False)
    assert (result["bad"]["evidence_lost"], result["bad"]["gate2"]) == (1, False)
    with pytest.raises(ValueError, match="no prediction"):
        evaluation.score(evalset, {"partial": {"c:1": {"relevant": 0.5}}})


def test_command_line_round_trip(store, case, tmp_path, capsys):
    sheet, evalset = tmp_path / "s.csv", tmp_path / "evalset.jsonl"
    root = ["--cases", str(store.root)]
    evaluation.main(root + ["cases"])
    assert case in capsys.readouterr().out
    evaluation.main(root + ["export", case, str(sheet)])
    evaluation.main(root + ["build", str(sheet), "--out", str(evalset)])
    preds = tmp_path / "model.jsonl"
    preds.write_text(json.dumps({"key": f"{case}:3", "relevant": 0.2}) + "\n", encoding="utf-8")
    evaluation.main(root + ["score", str(evalset), str(preds)])
    out = capsys.readouterr().out
    assert "1 items, 0 labelled relevant" in out and "model" in out and "entity matching" in out
