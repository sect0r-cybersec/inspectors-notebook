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
