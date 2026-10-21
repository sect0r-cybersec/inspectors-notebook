import io
import sys

import pytest
from PIL import Image

if sys.platform != "win32":
    pytest.skip("Windows only", allow_module_level=True)

from inspectors_notebook import screenshot


def page(colour, size=(1280, 720)):
    return Image.new("RGB", size, colour)


def test_thumbnail_is_small_greyscale():
    assert len(screenshot.thumbnail(page("white"))) == 32 * 18
    assert set(screenshot.thumbnail(page((255, 0, 0)))) == {76}


def test_first_capture_of_a_tab_counts_as_changed():
    assert screenshot.changed(None, screenshot.thumbnail(page("white")))


def test_small_changes_are_ignored_and_new_content_is_not():
    base = page((30, 30, 30))
    caret = base.copy()
    caret.paste((255, 255, 255), (600, 300, 602, 320))  # a blinking caret
    results = base.copy()
    results.paste((220, 220, 220), (0, 360, 1280, 720))  # a results grid fills the lower half
    assert not screenshot.changed(screenshot.thumbnail(base), screenshot.thumbnail(caret))
    assert screenshot.changed(screenshot.thumbnail(base), screenshot.thumbnail(results))


def test_webp_encoding():
    data = screenshot.encode_webp(page((0, 120, 200)))
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    assert Image.open(io.BytesIO(data)).size == (1280, 720)


def test_unknown_browsers_and_empty_titles_find_nothing():
    assert screenshot.find_window("safari", "Incidents") is None
    assert screenshot.find_window("chrome", "") is None
