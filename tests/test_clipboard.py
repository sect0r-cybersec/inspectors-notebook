import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows only", allow_module_level=True)

from inspectors_notebook import win32


def test_cf_html_offsets_point_at_the_fragment():
    data = win32._cf_html("<p>Héllo &amp; £</p>")
    header = dict(line.split(":", 1) for line in data.split(b"\r\n<html>")[0].decode("ascii").splitlines())
    start, end = int(header["StartFragment"]), int(header["EndFragment"])
    assert data[start:end].decode("utf-8") == "<p>Héllo &amp; £</p>"
    assert data[int(header["StartHTML"]):int(header["EndHTML"])].decode("utf-8").startswith("<html><body>")


@pytest.mark.desktop  # replaces whatever is on the clipboard
def test_text_round_trips_through_the_clipboard():
    win32.set_clipboard("Incident 4821 | £ and ünïcode", "<p>Incident 4821</p>")
    assert win32.get_clipboard_text() == "Incident 4821 | £ and ünïcode"
