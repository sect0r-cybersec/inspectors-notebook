import json

import pytest

from inspectors_notebook import settings as store
from inspectors_notebook.geometry import MAX_WIDTH
from inspectors_notebook.settings import Settings


def test_missing_file_gives_defaults(tmp_path):
    s = store.load(tmp_path / "settings.json")
    assert s == Settings(side="right", theme="dark", width=400, dock="appbar")


def test_round_trip_creates_parent_folder(tmp_path):
    path = tmp_path / "nested" / "settings.json"
    store.save(Settings(side="left", theme="system", width=480, dock="float"), path)
    assert store.load(path) == Settings(side="left", theme="system", width=480, dock="float")
    assert not path.with_suffix(".tmp").exists()


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", "null", ""])
def test_unreadable_file_gives_defaults(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")
    assert store.load(path) == Settings()


def test_invalid_fields_fall_back_one_by_one(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"side": "top", "theme": "light", "width": True, "dock": 3}), encoding="utf-8"
    )
    assert store.load(path) == Settings(theme="light")


def test_file_with_bom_is_read(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"side": "left"}), encoding="utf-8-sig")
    assert store.load(path).side == "left"


def test_width_is_clamped_on_load(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"width": 5000}), encoding="utf-8")
    assert store.load(path).width == MAX_WIDTH


def test_new_settings_have_the_agreed_defaults():
    s = Settings()
    assert (s.export_rows, s.interval_seconds, s.cache_size, s.dwell_seconds, s.preroll_minutes) == (5, 0, 5, 30, 3)
    assert (s.show_utc, s.screenshots, s.suggest_cases, s.warn_unexported, s.start_with_windows) == (False, True, True, True, False)


def test_changes_are_validated_like_the_file():
    s = store.changed(Settings(), {
        "cache_size": 0, "export_rows": 99, "interval_seconds": 5, "show_utc": True,
        "theme": "purple", "dwell_seconds": "30", "warn_unexported": 1, "unknown": True,
    })
    assert (s.cache_size, s.export_rows, s.interval_seconds, s.show_utc) == (1, 50, 15, True)
    assert (s.theme, s.dwell_seconds, s.warn_unexported) == ("dark", 30, True)
    assert store.changed(s, {"interval_seconds": 0}).interval_seconds == 0  # off
