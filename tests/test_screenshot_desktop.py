"""Captures a real window shown on the desktop. Opt-in: uv run pytest -m desktop"""

import ctypes
import sys
import threading
import time
from ctypes import wintypes

import pytest

if sys.platform != "win32":
    pytest.skip("Windows only", allow_module_level=True)

from inspectors_notebook import screenshot, win32

pytestmark = pytest.mark.desktop

gdi32 = ctypes.WinDLL("gdi32")
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]
user32 = ctypes.WinDLL("user32")
user32.SetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetClassLongPtrW.restype = ctypes.c_ssize_t
user32.InvalidateRect.argtypes = [wintypes.HWND, wintypes.LPVOID, wintypes.BOOL]
user32.UpdateWindow.argtypes = [wintypes.HWND]
GCLP_HBRBACKGROUND = -10
WS_VISIBLE = 0x10000000
TITLE = "Lab capture test - Google Chrome"


@pytest.fixture(scope="module", autouse=True)
def per_monitor_dpi():
    try:
        win32.enable_per_monitor_dpi()
    except OSError:
        pass


class BrowserLikeWindow:
    """A plain window with Chrome's window class and title style, filled with one colour."""

    def __init__(self, rgb):
        self.hwnd = 0
        self._ready = threading.Event()
        self._proc = win32.WNDPROC(self._wndproc)
        self._thread = threading.Thread(target=self._run, args=(rgb,), daemon=True)
        self._thread.start()
        self._ready.wait(5)
        time.sleep(0.3)  # let DWM compose the first frame

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == win32.WM_DESTROY:
            win32.PostQuitMessage(0)
            return 0
        return win32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self, rgb):
        hinst = win32.GetModuleHandleW(None)
        wc = win32.WNDCLASSEXW(
            cbSize=ctypes.sizeof(win32.WNDCLASSEXW), lpfnWndProc=self._proc, hInstance=hinst,
            lpszClassName="Chrome_WidgetWin_1", hbrBackground=gdi32.CreateSolidBrush(win32.colorref(rgb)),
        )  # fmt: skip
        win32.RegisterClassExW(ctypes.byref(wc))
        self.hwnd = win32.CreateWindowExW(
            0, "Chrome_WidgetWin_1", TITLE, win32.WS_POPUP | WS_VISIBLE, 120, 120, 480, 320, None, None, hinst, None
        )
        self._ready.set()
        msg = wintypes.MSG()
        while win32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            win32.TranslateMessage(ctypes.byref(msg))
            win32.DispatchMessageW(ctypes.byref(msg))
        win32.UnregisterClassW("Chrome_WidgetWin_1", hinst)

    def fill(self, rgb):
        user32.SetClassLongPtrW(self.hwnd, GCLP_HBRBACKGROUND, gdi32.CreateSolidBrush(win32.colorref(rgb)))
        user32.InvalidateRect(self.hwnd, None, True)
        user32.UpdateWindow(self.hwnd)
        time.sleep(0.3)

    def close(self):
        # Wait for the class to be unregistered: the next window registers the same
        # class name, and must not inherit this one's window procedure.
        win32.PostMessageW(self.hwnd, win32.WM_CLOSE, 0, 0)
        self._thread.join(5)


@pytest.fixture
def window():
    w = BrowserLikeWindow("#C0392B")
    yield w
    w.close()


def test_finds_browser_window_by_class_and_tab_title(window):
    assert screenshot.find_window("chrome", "Lab capture test") == window.hwnd
    assert screenshot.find_window("edge", "Lab capture test") == window.hwnd  # same window class
    assert screenshot.find_window("firefox", "Lab capture test") is None
    assert screenshot.find_window("chrome", "Another tab") is None


def test_captures_the_window_pixels(window):
    image = screenshot.capture_window(window.hwnd)
    assert image.width > 400 and image.height > 250
    assert image.getpixel((image.width // 2, image.height // 2)) == (0xC0, 0x39, 0x2B)


def test_unchanged_window_is_skipped_and_changed_one_captured(window):
    shooter = screenshot.Screenshotter()
    first = shooter.capture("chrome", ("src", 1), "Lab capture test")
    assert first is not None and first.webp[8:12] == b"WEBP"
    assert shooter.capture("chrome", ("src", 1), "Lab capture test") is None
    assert shooter.capture("chrome", ("src", 2), "Lab capture test") is not None  # another tab
    window.fill("#2E86C1")
    assert shooter.capture("chrome", ("src", 1), "Lab capture test") is not None
