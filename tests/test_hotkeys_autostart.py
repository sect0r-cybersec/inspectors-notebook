import sys
import time
import winreg

import pytest

if sys.platform != "win32":
    pytest.skip("Windows only", allow_module_level=True)

from inspectors_notebook import autostart, hotkeys

TEST_KEY = r"Software\InspectorsNotebookTest\Run"


@pytest.fixture
def run_key():
    yield TEST_KEY
    for path in (TEST_KEY, r"Software\InspectorsNotebookTest"):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass


def test_start_with_windows_adds_and_removes_the_run_entry(run_key):  # FR-38
    assert not autostart.is_enabled(run_key)
    autostart.set_enabled(True, run_key)
    assert autostart.is_enabled(run_key)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key) as key:
        value = winreg.QueryValueEx(key, autostart.VALUE)[0]
    assert value.endswith('pythonw.exe" -m inspectors_notebook') and value.startswith('"')
    autostart.set_enabled(False, run_key)
    autostart.set_enabled(False, run_key)  # already off
    assert not autostart.is_enabled(run_key)


def test_shortcut_labels_use_ctrl_alt():
    assert [hotkeys.label(n) for n in ("note", "record", "panel")] == ["Ctrl+Alt+N", "Ctrl+Alt+S", "Ctrl+Alt+I"]


@pytest.mark.desktop
def test_shortcuts_register_and_dispatch():
    pressed = []
    keys = hotkeys.Hotkeys({name: (lambda n=name: pressed.append(n)) for name in ("note", "record", "panel")})
    try:
        unavailable = keys.start()  # another program may hold a combination on any machine
        available = [i for i, (name, _) in hotkeys.SHORTCUTS.items() if name not in unavailable]
        assert available, "every shortcut is held by another program"
        # A real key press is posted as WM_HOTKEY to the registering thread; do the same.
        for hotkey_id in available:
            hotkeys.user32.PostThreadMessageW(keys._thread_id, hotkeys.WM_HOTKEY, hotkey_id, 0)
        deadline = time.monotonic() + 2
        while len(pressed) < len(available) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert pressed == [hotkeys.SHORTCUTS[i][0] for i in available]
    finally:
        keys.stop()
