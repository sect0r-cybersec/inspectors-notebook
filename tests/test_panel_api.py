import pytest

from inspectors_notebook import settings as store
from inspectors_notebook.geometry import MIN_WIDTH, RAIL_WIDTH, Layout
from inspectors_notebook.case_store import CaseStore
from inspectors_notebook.cases import CaseManager
from inspectors_notebook.panel import PanelApi
from inspectors_notebook.settings import Settings


class FakeDock:
    def __init__(self):
        self.applied: list[Layout] = []
        self.previewed: list[Layout] = []
        self.themes: list[str] = []

    def apply(self, layout):
        self.applied.append(layout)

    def preview(self, layout):
        self.previewed.append(layout)

    def set_theme(self, theme):
        self.themes.append(theme)


@pytest.fixture
def path(tmp_path):
    return tmp_path / "settings.json"


def make_api(path, windows_light=False, **settings):
    dock = FakeDock()
    api = PanelApi(Settings(**settings), path, dock, lambda: windows_light)
    return api, dock


def test_initial_state(path):
    api, _ = make_api(path)
    assert api.get_state() == {
        "side": "right",
        "theme": "dark",
        "width": 400,
        "collapsed": False,
        "listener": {"browsers": 0, "tabs": 0},
        "case": None,
        "suggestion": None,
        "timeline": [],
    }


def test_toggle_side_docks_and_is_remembered(path):
    api, dock = make_api(path)
    assert api.toggle_side()["side"] == "left"
    assert dock.applied[-1] == Layout("left", 400, "appbar")
    assert store.load(path).side == "left"
    assert api.toggle_side()["side"] == "right"
    assert dock.applied[-1] == Layout("right", 400, "appbar")


def test_collapse_shrinks_to_rail_and_expand_restores(path):
    api, dock = make_api(path, width=480)
    assert api.toggle_collapse()["collapsed"] is True
    assert dock.applied[-1] == Layout("right", RAIL_WIDTH, "appbar")
    assert api.toggle_collapse()["collapsed"] is False
    assert dock.applied[-1] == Layout("right", 480, "appbar")


def test_side_switch_while_collapsed_keeps_rail(path):
    api, dock = make_api(path)
    api.toggle_collapse()
    api.toggle_side()
    assert dock.applied[-1] == Layout("left", RAIL_WIDTH, "appbar")


def test_toggle_theme_flips_and_is_remembered(path):
    api, dock = make_api(path)
    assert api.toggle_theme()["theme"] == "light"
    assert dock.themes == ["light"]
    assert store.load(path).theme == "light"
    assert api.toggle_theme()["theme"] == "dark"


@pytest.mark.parametrize(("windows_light", "expected"), [(True, "light"), (False, "dark")])
def test_system_theme_follows_windows(path, windows_light, expected):
    api, _ = make_api(path, windows_light=windows_light, theme="system")
    assert api.get_state()["theme"] == expected


def test_toggle_from_system_switches_away_from_windows_theme(path):
    api, _ = make_api(path, windows_light=True, theme="system")
    assert api.toggle_theme()["theme"] == "dark"
    assert store.load(path).theme == "dark"


def test_preview_width_does_not_save(path):
    api, dock = make_api(path)
    api.preview_width(500)
    assert dock.previewed == [Layout("right", 500, "appbar")]
    assert not path.exists()


def test_preview_width_ignored_while_collapsed(path):
    api, dock = make_api(path)
    api.toggle_collapse()
    api.preview_width(500)
    assert dock.previewed == []


def test_set_width_clamps_saves_and_docks(path):
    api, dock = make_api(path)
    assert api.set_width(10)["width"] == MIN_WIDTH
    assert dock.applied[-1] == Layout("right", MIN_WIDTH, "appbar")
    assert store.load(path).width == MIN_WIDTH


def test_listener_state_is_reported(path):
    api, _ = make_api(path)
    api._set_listener({"browsers": 2, "tabs": 5})
    assert api.get_state()["listener"] == {"browsers": 2, "tabs": 5}


def test_expand_only_redocks_when_collapsed(path):
    api, dock = make_api(path)
    api._expand()
    assert dock.applied == []
    api.toggle_collapse()
    api._expand()
    assert api.get_state()["collapsed"] is False
    assert dock.applied[-1] == Layout("right", 400, "appbar")


def test_case_controls_drive_the_case_manager(path, tmp_path):
    cases = CaseManager(CaseStore(tmp_path / "cases"))
    api = PanelApi(Settings(), path, FakeDock(), lambda: False, cases)
    form = {"incidentId": " 4821 ", "title": "Suspicious PowerShell", "entities": "HOST-12, j.smith\n203.0.113.7\n"}
    state = api.start_case(form)
    assert state["case"]["incidentId"] == "4821"
    assert state["case"]["entities"] == ["HOST-12", "j.smith", "203.0.113.7"]
    assert api.pause_case()["case"]["state"] == "paused"
    assert api.resume_case()["case"]["state"] == "recording"
    assert api.add_entity("evil.exe")["case"]["entities"][-1] == "evil.exe"
    assert "j.smith" not in api.remove_entity("j.smith")["case"]["entities"]
    assert api.stop_case()["case"] is None


def test_timeline_actions_and_settings(path, tmp_path):
    cases = CaseManager(CaseStore(tmp_path / "cases"))
    dock = FakeDock()
    api = PanelApi(Settings(), path, dock, lambda: False, cases)
    settings_changed, autostart = [], []
    api._on_settings = lambda: settings_changed.append(True)
    api._autostart = autostart.append
    api.start_case({"title": "Case", "entities": "HOST-12"})
    state = api.add_note("Saw HOST-12 beaconing")
    [note] = state["timeline"]
    assert (note["kind"], note["text"], note["reason"]) == ("note", "Saw HOST-12 beaconing", "entity")
    state = api.star_item(note["ids"], True)
    assert state["timeline"][0]["star"] and state["case"]["counts"]["findings"] == 1
    assert api.comment_item(note["ids"], "Beacon every 60 s")["timeline"][0]["annotation"] == "Beacon every 60 s"
    assert api.decide_item(note["ids"], "hide")["timeline"][0]["disposition"] == "hide"
    assert api.decide_item(note["ids"], None)["timeline"][0]["disposition"] == "keep"

    preview = api.export_preview({"fmt": "markdown"})
    assert preview["text"].startswith("# Case") and preview["findings"] == 1 and preview["rowLimit"] == 5

    out = api.update_settings({"show_utc": True, "side": "left", "start_with_windows": True, "cache_size": 99})
    assert (out["show_utc"], out["side"], out["start_with_windows"], out["cache_size"]) == (True, "left", True, 50)
    assert dock.applied[-1].side == "left" and autostart == [True] and settings_changed == [True]
    assert store.load(path).show_utc is True
    assert "UTC" in api.get_state()["timeline"][0]["time"]
