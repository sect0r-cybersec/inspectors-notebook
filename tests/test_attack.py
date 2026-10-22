"""ATT&CK tactic tags: the analyst tags events, and the tags reach the panel and every export."""

from datetime import timedelta, timezone

from inspectors_notebook import attack, export, timeline
from inspectors_notebook.case_store import CaseStore
from inspectors_notebook.cases import CaseManager
from inspectors_notebook.panel import PanelApi
from inspectors_notebook.settings import Settings

TZ = timezone(timedelta(hours=1))


def at(hhmm):
    return f"2026-10-22T{hhmm}:00.000+01:00"


class Dock:
    def apply(self, layout): ...
    def preview(self, layout): ...
    def set_theme(self, theme): ...


def make_case(tmp_path):
    clock = {"now": at("10:00")}
    m = CaseManager(CaseStore(tmp_path / "cases"), now=lambda: clock["now"])
    m.start(title="Lateral movement from HOST-12", entities=["HOST-12"])
    clock["now"] = at("10:05")
    m.add_note("RDP from HOST-12 to DC01 as jdoe")
    clock["now"] = at("10:07")
    m.add_note("jdoe ran nltest /dclist")
    return m


def items_of(m):
    return timeline.build([e for e, _ in m.events()], [d for _, d in m.events()], m.marks())


def test_the_v20_tactics_in_matrix_order():
    assert len(attack.TACTICS) == 15
    assert list(attack.TACTICS)[:3] == ["TA0043", "TA0042", "TA0001"] and list(attack.TACTICS)[-1] == "TA0040"
    assert attack.TACTICS["TA0005"] == "Stealth" and attack.TACTICS["TA0112"] == "Defense Impairment"  # v20 split Defense Evasion


def test_tags_are_known_ids_once_each_in_matrix_order():
    assert attack.clean(["TA0008", "TA0001", "TA0008", "T1021", "", 7]) == ["TA0001", "TA0008"]
    assert attack.clean("TA0008") == [] and attack.clean(None) == []


def test_tags_are_kept_with_the_case_and_cleared_when_emptied(tmp_path):
    m = make_case(tmp_path)
    m.set_tactics(1, ["TA0008", "TA0001"])
    m.set_tactics(2, ["TA0007"])
    m.set_tactics(2, [])
    _, _, marks = m._store.load(m.case_meta()["id"])  # as the case is reopened from disk
    assert marks[1]["tactics"] == ["TA0001", "TA0008"] and "tactics" not in marks.get(2, {})
    assert [i.tactics for i in items_of(m)] == [("TA0001", "TA0008"), ()]


def test_the_panel_lists_the_tactics_and_tags_an_item(tmp_path):
    m = make_case(tmp_path)
    api = PanelApi(Settings(), tmp_path / "settings.json", Dock(), lambda: False, m)
    listed = api.tactics()
    assert listed["version"] == "v20" and listed["tactics"][6] == {"id": "TA0005", "name": "Stealth"}
    state = api.tag_item([1], ["TA0008"])
    note = next(i for i in state["timeline"] if i["ids"] == [1])
    assert note["tactics"] == [{"id": "TA0008", "name": "Lateral Movement"}]
    assert api.tag_item([1], "TA0008")["timeline"][-1]["tactics"] == []  # not a list: cleared


def test_every_export_format_shows_the_tags(tmp_path):
    m = make_case(tmp_path)
    m.set_tactics(1, ["TA0008"])
    m.set_star(1, True)
    m.set_tactics(2, ["TA0007", "TA0006"])
    items = items_of(m)
    text = export.render(m.case_meta(), items, export.Options(fmt="text", tz=TZ))
    assert "ATT&CK tactics (v20): Credential Access, Discovery, Lateral Movement\n" in text
    assert "KEY FINDINGS\n10:05  RDP from HOST-12 to DC01 as jdoe [Lateral Movement]\n" in text
    assert "10:07  NOTE     jdoe ran nltest /dclist\n                ATT&CK: Credential Access (TA0006), Discovery (TA0007)\n" in text
    md = export.render(m.case_meta(), items, export.Options(fmt="markdown", tz=TZ))
    assert "- **10:05** Note: RDP from HOST-12 to DC01 as jdoe\n\n  ATT&CK: Lateral Movement (TA0008)\n" in md
    assert "ATT&CK tactics (v20): Credential Access, Discovery, Lateral Movement\n" in md
    html = export.render(m.case_meta(), items, export.Options(fmt="html", tz=TZ))
    assert "<p>ATT&amp;CK: Lateral Movement (TA0008)</p>" in html and "<p>ATT&amp;CK tactics (v20):" in html


def test_untagged_cases_export_as_before(tmp_path):
    out = export.render(make_case(tmp_path).case_meta(), items_of(make_case(tmp_path)), export.Options(tz=TZ))
    assert "ATT&CK" not in out
