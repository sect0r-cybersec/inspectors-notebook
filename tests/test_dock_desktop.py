"""Docks a real window against the real Windows shell.

These rearrange the windows on the desktop while they run, so they are opt-in:
    uv run pytest -m desktop
"""

import ctypes
import sys
import threading
import time
from ctypes import wintypes

import pytest

if sys.platform != "win32":
    pytest.skip("Windows only", allow_module_level=True)

from inspectors_notebook import win32
from inspectors_notebook.dock import Dock
from inspectors_notebook.geometry import INSET, RAIL_WIDTH, Layout, strip_width, to_physical

pytestmark = pytest.mark.desktop

_CLASS = "InspectorsNotebook.TestPanel"


@pytest.fixture(scope="module", autouse=True)
def per_monitor_dpi():
    try:
        win32.enable_per_monitor_dpi()
    except OSError:
        pass  # already set for this process


class FakePanel:
    """A plain visible popup window with its own message loop, standing in for pywebview."""

    def __init__(self):
        self.hwnd = 0
        self._ready = threading.Event()
        self._proc = win32.WNDPROC(self._wndproc)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == win32.WM_DESTROY:
            win32.PostQuitMessage(0)
            return 0
        return win32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self):
        hinst = win32.GetModuleHandleW(None)
        wc = win32.WNDCLASSEXW(
            cbSize=ctypes.sizeof(win32.WNDCLASSEXW), lpfnWndProc=self._proc,
            hInstance=hinst, lpszClassName=_CLASS,
        )  # fmt: skip
        win32.RegisterClassExW(ctypes.byref(wc))
        WS_VISIBLE = 0x10000000
        self.hwnd = win32.CreateWindowExW(
            win32.WS_EX_TOOLWINDOW, _CLASS, "Test panel", win32.WS_POPUP | WS_VISIBLE,
            100, 100, 200, 200, None, None, hinst, None,
        )  # fmt: skip
        self._ready.set()
        msg = wintypes.MSG()
        while win32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            win32.TranslateMessage(ctypes.byref(msg))
            win32.DispatchMessageW(ctypes.byref(msg))
        win32.UnregisterClassW(_CLASS, hinst)

    def close(self):
        win32.PostMessageW(self.hwnd, win32.WM_CLOSE, 0, 0)
        self._thread.join(5)


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


@pytest.fixture
def panel():
    p = FakePanel()
    yield p
    p.close()


@pytest.fixture
def dock(panel):
    d = Dock()
    yield d
    d.stop()


def work_area(panel):
    return win32.monitor_of(panel.hwnd)[1]


def test_dock_switch_sides_collapse_and_undock(panel, dock):
    monitor, before, dpi = win32.monitor_of(panel.hwnd)
    inset = to_physical(INSET, dpi)
    strip = strip_width(400, dpi)

    dock.start(panel.hwnd, Layout("right", 400, "appbar"), "dark")
    assert dock.flush()
    assert wait_for(lambda: work_area(panel).right == before.right - strip)
    assert wait_for(lambda: win32.window_rect(panel.hwnd).width == to_physical(400, dpi))
    rect = win32.window_rect(panel.hwnd)
    assert rect.right == before.right - inset
    assert rect.top == before.top + inset
    assert rect.bottom == before.bottom - inset

    dock.apply(Layout("left", 400, "appbar"))
    assert dock.flush()
    assert wait_for(lambda: work_area(panel).left == before.left + strip)
    assert work_area(panel).right == before.right
    assert wait_for(lambda: win32.window_rect(panel.hwnd).left == before.left + inset)

    dock.apply(Layout("left", RAIL_WIDTH, "appbar"))
    assert dock.flush()
    assert wait_for(lambda: work_area(panel).left == before.left + strip_width(RAIL_WIDTH, dpi))
    assert wait_for(lambda: win32.window_rect(panel.hwnd).width == to_physical(RAIL_WIDTH, dpi))

    dock.apply(Layout("left", 400, "float"))
    assert dock.flush()
    assert wait_for(lambda: work_area(panel) == before)
    assert wait_for(lambda: win32.window_rect(panel.hwnd).width == to_physical(400, dpi))


def test_stop_releases_reserved_strip(panel, dock):
    before = work_area(panel)
    dock.start(panel.hwnd, Layout("right", 400, "appbar"), "dark")
    assert dock.flush()
    assert wait_for(lambda: work_area(panel) != before)
    dock.stop()
    assert wait_for(lambda: work_area(panel) == before)


def test_preview_moves_panel_without_reserving(panel, dock):
    _, before, dpi = win32.monitor_of(panel.hwnd)
    dock.start(panel.hwnd, Layout("right", 400, "appbar"), "dark")
    assert dock.flush()
    assert wait_for(lambda: work_area(panel).right == before.right - strip_width(400, dpi))

    dock.preview(Layout("right", 500, "appbar"))
    assert dock.flush()
    assert wait_for(lambda: win32.window_rect(panel.hwnd).width == to_physical(500, dpi))
    assert work_area(panel).right == before.right - strip_width(400, dpi)
