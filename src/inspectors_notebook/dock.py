"""Docks the panel window to a screen edge as a Windows AppBar (FR-48 to FR-52).

Every shell call runs on one thread that owns a hidden helper window. The helper is
registered as the AppBar, so it receives the shell's callbacks, display changes and
resume-from-sleep broadcasts, and re-docks the panel in response. Callers on other
threads post requests to it; only the latest request is acted on.
"""

import ctypes
import logging
import threading
from ctypes import wintypes

from . import win32
from .geometry import INSET, Layout, Rect, edge_strip, panel_rect, restore_width, strip_width, to_physical

log = logging.getLogger(__name__)

BORDER_COLOURS = {"dark": "#2A3038", "light": "#DDE1E6"}

_WM_APPBAR_CALLBACK = win32.WM_APP + 1
_WM_REFLOW = win32.WM_APP + 2
_WM_PREVIEW = win32.WM_APP + 3
_WM_FLUSH = win32.WM_APP + 4
_CLASS_NAME = "InspectorsNotebook.DockHelper"


class Dock:
    def __init__(self) -> None:
        self._panel = 0
        self._helper = 0
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._layout: Layout | None = None
        self._preview: Layout | None = None
        self._flushed: list[threading.Event] = []
        self._registered = False
        self._strip: Rect | None = None  # last strip given to the shell, physical px
        self._topmost = True
        self._wndproc = win32.WNDPROC(self._handle)  # keep a reference for the window's lifetime
        self._error: BaseException | None = None

    # Public API, safe from any thread

    def start(self, panel_hwnd: int, layout: Layout, theme: str) -> None:
        self._panel = panel_hwnd
        self._layout = layout
        self.set_theme(theme)
        self._thread = threading.Thread(target=self._run, name="dock", daemon=True)
        self._thread.start()
        self._ready.wait()
        if self._error:
            raise self._error
        self._post(_WM_REFLOW)

    def apply(self, layout: Layout) -> None:
        with self._lock:
            self._layout = layout
            self._preview = None
        self._post(_WM_REFLOW)

    def preview(self, layout: Layout) -> None:
        """Move and size the panel without asking the shell to reserve space."""
        with self._lock:
            self._preview = layout
        self._post(_WM_PREVIEW)

    def set_theme(self, theme: str) -> None:
        win32.style_window_frame(self._panel, BORDER_COLOURS[theme])

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until every request posted so far has been handled."""
        done = threading.Event()
        with self._lock:
            self._flushed.append(done)
        self._post(_WM_FLUSH)
        return done.wait(timeout)

    def stop(self) -> None:
        """Release the reserved strip and end the helper thread."""
        if self._helper:
            win32.PostMessageW(self._helper, win32.WM_CLOSE, 0, 0)
        if self._thread:
            self._thread.join(timeout=5)

    # Helper thread

    def _post(self, msg: int) -> None:
        if self._helper:
            win32.PostMessageW(self._helper, msg, 0, 0)

    def _run(self) -> None:
        hinst = win32.GetModuleHandleW(None)
        try:
            wc = win32.WNDCLASSEXW(
                cbSize=ctypes.sizeof(win32.WNDCLASSEXW),
                lpfnWndProc=self._wndproc,
                hInstance=hinst,
                lpszClassName=_CLASS_NAME,
            )
            if not win32.RegisterClassExW(ctypes.byref(wc)):
                raise ctypes.WinError(ctypes.get_last_error())
            # A hidden top-level window rather than a message-only one, because only
            # top-level windows receive WM_DISPLAYCHANGE and WM_POWERBROADCAST.
            self._helper = win32.CreateWindowExW(
                win32.WS_EX_TOOLWINDOW, _CLASS_NAME, "Inspector's Notebook dock",
                win32.WS_POPUP, 0, 0, 0, 0, None, None, hinst, None,
            )  # fmt: skip
            if not self._helper:
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException as e:
            self._error = e
            self._ready.set()
            return
        self._ready.set()

        msg = wintypes.MSG()
        while win32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            win32.TranslateMessage(ctypes.byref(msg))
            win32.DispatchMessageW(ctypes.byref(msg))
        self._helper = 0
        win32.UnregisterClassW(_CLASS_NAME, hinst)

    def _handle(self, hwnd, msg, wparam, lparam):
        try:
            if msg == _WM_REFLOW:
                self._reflow()
                return 0
            if msg == _WM_PREVIEW:
                self._show_preview()
                return 0
            if msg == _WM_FLUSH:
                with self._lock:
                    flushed, self._flushed = self._flushed, []
                for done in flushed:
                    done.set()
                return 0
            if msg == _WM_APPBAR_CALLBACK:
                if wparam == win32.ABN_POSCHANGED:
                    self._reflow()
                elif wparam == win32.ABN_FULLSCREENAPP:
                    # Step out of the way of full-screen apps, come back on top afterwards.
                    self._topmost = not lparam
                    self._reflow()
                return 0
            if msg == win32.WM_DISPLAYCHANGE:
                self._reflow()
            elif msg == win32.WM_POWERBROADCAST and wparam in (
                win32.PBT_APMRESUMEAUTOMATIC,
                win32.PBT_APMRESUMESUSPEND,
            ):
                log.info("Resumed from sleep; re-docking")
                self._reflow()
            elif msg == win32.WM_CLOSE:
                self._unregister()
                win32.DestroyWindow(hwnd)
                return 0
            elif msg == win32.WM_DESTROY:
                win32.PostQuitMessage(0)
                return 0
        except Exception:
            log.exception("Dock message %#x failed", msg)
            return 0
        return win32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _appbar_data(self, side: str | None = None, rc: Rect | None = None) -> win32.APPBARDATA:
        abd = win32.APPBARDATA(cbSize=ctypes.sizeof(win32.APPBARDATA), hWnd=self._helper)
        if side:
            abd.uEdge = win32.ABE_RIGHT if side == "right" else win32.ABE_LEFT
        if rc:
            abd.rc = win32.RECT.from_rect(rc)
        return abd

    def _register(self) -> bool:
        if not self._registered:
            abd = self._appbar_data()
            abd.uCallbackMessage = _WM_APPBAR_CALLBACK
            self._registered = bool(win32.SHAppBarMessage(win32.ABM_NEW, ctypes.byref(abd)))
            if not self._registered:
                log.warning("The shell refused the AppBar; floating on top instead")
        return self._registered

    def _unregister(self) -> None:
        if self._registered:
            win32.SHAppBarMessage(win32.ABM_REMOVE, ctypes.byref(self._appbar_data()))
            self._registered = False
            self._strip = None

    def _reflow(self) -> None:
        with self._lock:
            layout, previewing = self._layout, self._preview is not None
        if layout is None:
            return
        monitor, work, dpi = win32.monitor_of(self._panel)
        width = strip_width(layout.width, dpi)

        if layout.mode == "appbar" and self._register():
            abd = self._appbar_data(layout.side, edge_strip(monitor, layout.side, width))
            win32.SHAppBarMessage(win32.ABM_QUERYPOS, ctypes.byref(abd))
            abd.rc = win32.RECT.from_rect(restore_width(abd.rc.to_rect(), layout.side, width))
            win32.SHAppBarMessage(win32.ABM_SETPOS, ctypes.byref(abd))
            strip = abd.rc.to_rect()
            self._strip = strip
            _, work, _ = win32.monitor_of(self._panel)  # now excludes our strip
        else:
            self._unregister()
            strip = edge_strip(work, layout.side, width)

        # The shell sends ABN_POSCHANGED after our own SETPOS too; if that lands
        # mid-drag, keep the width being dragged rather than snapping back.
        if previewing:
            self._show_preview()
        else:
            self._place(panel_rect(strip, work, to_physical(INSET, dpi)))

    def _show_preview(self) -> None:
        with self._lock:
            layout, base = self._preview, self._layout
        if layout is None or base is None:
            return
        monitor, work, dpi = win32.monitor_of(self._panel)
        width = strip_width(layout.width, dpi)
        outer = self._strip if self._strip and base.mode == "appbar" else edge_strip(work, layout.side, width)
        self._place(panel_rect(restore_width(outer, layout.side, width), work, to_physical(INSET, dpi)))

    def _place(self, rc: Rect) -> None:
        after = win32.HWND_TOPMOST if self._topmost else win32.HWND_NOTOPMOST
        flags = win32.SWP_NOACTIVATE | win32.SWP_ASYNCWINDOWPOS
        win32.SetWindowPos(self._panel, after, rc.left, rc.top, rc.width, rc.height, flags)
