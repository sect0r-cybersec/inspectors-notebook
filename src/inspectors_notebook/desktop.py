"""Desktop capture (S9, FR-45 to FR-47): text from apps the analyst has allowed.

Off by default. Only while a case is recording, only the window in front, and only apps
the analyst has allowed in Settings (by program name, such as WindowsTerminal.exe or
mstsc.exe), so it works with any terminal, RDP client or thick client without per-app rules.

Text comes from Windows UI Automation where the app exposes it (terminals and many thick
clients): exact, and only what is on screen. RDP and VDI windows are pixels only, so
Windows' built-in OCR reads those instead, and that text is marked approximate: in testing
it dropped or garbled IP addresses. Both come with Windows and .NET Framework, reached
through pythonnet, which pywebview already loads. Nothing leaves the machine.

Each poll sends only lines that were not on screen before, as one event that goes through
the same rules as browser events (FR-47); switching to an allowed window is an event too.
"""

import ctypes
import difflib
import logging
import os
import re
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)

INTERVAL = 3.0  # seconds between looks at the window in front
MAX_TEXT = 4000  # characters per event
SIMILAR = 0.9  # a line this close to one already seen is OCR jitter, not new text
APP_NAME = re.compile(r"^[\w .()-]{1,64}\.exe$", re.IGNORECASE)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x80
DWMWA_CLOAKED = 14
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


@dataclass(frozen=True)
class Window:
    hwnd: int
    pid: int
    app: str  # program file name, such as mstsc.exe
    title: str


def _process_name(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(handle)


def window_info(hwnd: int) -> Window | None:
    if not hwnd or user32.IsIconic(hwnd) or not user32.IsWindowVisible(hwnd):
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    length = user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title, length + 1)
    return Window(int(hwnd), pid.value, _process_name(pid.value), title.value)


def foreground_window() -> Window | None:
    return window_info(user32.GetForegroundWindow())


def _app_window(hwnd: int) -> bool:
    """A window the analyst sees and switches to: not owned, not a tool window, not hidden by Windows."""
    if user32.GetWindow(hwnd, GW_OWNER) or user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
        return False
    cloaked = wintypes.DWORD()
    dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return not cloaked.value


def open_apps() -> list[dict]:
    """Programs with a window open, for the allow list in Settings."""
    seen: dict[str, str] = {}

    def visit(hwnd, _):
        info = window_info(hwnd)
        if info and info.title and info.app and info.pid != os.getpid() and _app_window(hwnd):
            seen.setdefault(info.app, info.title)
        return True

    user32.EnumWindows(WNDENUMPROC(visit), 0)
    return [{"app": app, "title": title} for app, title in sorted(seen.items(), key=lambda kv: kv[0].lower())]


# Readers


class UiaReader:
    """Text on screen from UI Automation's text pattern, where the app provides one."""

    def __init__(self) -> None:
        import clr  # pythonnet, as loaded by pywebview

        clr.AddReference("UIAutomationClient, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35")
        clr.AddReference("UIAutomationTypes, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35")
        from System import IntPtr
        from System.Windows.Automation import AutomationElement, PropertyCondition, TextPattern, TreeScope

        self._IntPtr, self._Element, self._TextPattern, self._Subtree = IntPtr, AutomationElement, TextPattern, TreeScope.Subtree
        self._has_text = PropertyCondition(AutomationElement.IsTextPatternAvailableProperty, True)

    def read(self, hwnd: int) -> str | None:
        element = self._Element.FromHandle(self._IntPtr(hwnd))
        texts = []
        for found in element.FindAll(self._Subtree, self._has_text):
            pattern = found.GetCurrentPattern(self._TextPattern.Pattern)
            texts.append("\n".join(r.GetText(-1) for r in pattern.GetVisibleRanges()))
        best = max(texts, key=len, default="")
        return best if best.strip() else None


class OcrReader:
    """Text on screen from Windows' built-in OCR (Windows.Media.Ocr), in the user's languages."""

    def __init__(self) -> None:
        import clr

        clr.AddReference("System.Runtime.WindowsRuntime, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089")
        from System import Array, Byte, Type

        # WinRT types load by type name on .NET Framework; then they can be imported.
        for qualified in ("Windows.Media.Ocr.OcrEngine, Windows.Media", "Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics"):
            if Type.GetType(f"{qualified}, ContentType=WindowsRuntime") is None:
                raise RuntimeError(f"{qualified} is not available")
        from System import WindowsRuntimeSystemExtensions
        from System.Runtime.InteropServices.WindowsRuntime import WindowsRuntimeBufferExtensions
        from Windows.Graphics.Imaging import BitmapPixelFormat, SoftwareBitmap
        from Windows.Media.Ocr import OcrEngine, OcrResult

        self._engine = OcrEngine.TryCreateFromUserProfileLanguages()
        if self._engine is None:
            raise RuntimeError("no OCR language is installed")
        self._limit = OcrEngine.MaxImageDimension
        self._bytes = lambda data: Array[Byte](data)
        self._buffer = WindowsRuntimeBufferExtensions.AsBuffer
        self._bitmap = lambda buf, w, h: SoftwareBitmap.CreateCopyFromBuffer(buf, BitmapPixelFormat.Bgra8, w, h)
        self._wait = lambda op: WindowsRuntimeSystemExtensions.AsTask[OcrResult](op)

    def recognise(self, image) -> str:
        image = image.convert("RGBA")
        if max(image.size) > self._limit:
            image.thumbnail((self._limit, self._limit))
        bitmap = self._bitmap(self._buffer(self._bytes(image.tobytes("raw", "BGRA"))), image.width, image.height)
        task = self._wait(self._engine.RecognizeAsync(bitmap))
        task.Wait()
        return "\n".join(line.Text for line in task.Result.Lines)

    def read(self, hwnd: int) -> str | None:
        from .screenshot import capture_window

        text = self.recognise(capture_window(hwnd))
        return text if text.strip() else None


# What is new on screen


def screen_lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]


def new_lines(seen: list[str], current: list[str]) -> list[str]:
    """Lines on screen now that were not there before, in order, ignoring near-repeats."""
    added = []
    for op, _, _, j1, j2 in difflib.SequenceMatcher(a=seen, b=current, autojunk=False).get_opcodes():
        if op in ("insert", "replace"):
            added += current[j1:j2]
    return [line for line in added if not difflib.get_close_matches(line, seen, n=1, cutoff=SIMILAR)]


# The capture loop


class DesktopCapture:
    def __init__(
        self,
        ingest: Callable[[dict], None],
        recording: Callable[[], bool],
        settings: Callable,
        now: Callable[[], str],
        foreground: Callable[[], Window | None] = foreground_window,
        uia: Callable[[], object] = UiaReader,
        ocr: Callable[[], object] = OcrReader,
        interval: float = INTERVAL,
    ):
        self._ingest = ingest
        self._recording = recording
        self._settings = settings
        self._now = now
        self._foreground = foreground
        self._make = {"uia": uia, "ocr": ocr}
        self._readers: dict[str, object | None] = {}
        self._interval = interval
        self._seq = 0
        self._current: int | None = None  # the window last switched to
        self._seen: dict[int, list[str]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="desktop", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(2)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.poll()
            except Exception:
                log.exception("Desktop capture failed")

    def _reader(self, method: str):
        """Readers load once, on first use; one that cannot load is not tried again."""
        if method not in self._readers:
            try:
                self._readers[method] = self._make[method]()
            except Exception as e:
                log.warning("Desktop capture: %s is unavailable: %s", method, e)
                self._readers[method] = None
        return self._readers[method]

    def _read(self, window: Window) -> tuple[str | None, str | None]:
        for method in ("uia", "ocr"):
            reader = self._reader(method)
            if reader is None:
                continue
            try:
                text = reader.read(window.hwnd)
            except Exception as e:
                log.debug("Desktop capture: %s could not read %s: %s", method, window.app, e)
                continue
            if text:
                return text, method
        return None, None

    def _event(self, kind: str, window: Window, **fields) -> dict:
        self._seq += 1
        return {
            "type": "event", "kind": kind, "source": "desktop", "seq": self._seq, "ts": self._now(),
            "app": window.app, "title": window.title, **fields,
        }  # fmt: skip

    def poll(self) -> None:
        """One look at the window in front."""
        s = self._settings()
        if not s.desktop_capture or not self._recording():
            self._current = None
            return
        window = self._foreground()
        allowed = {a.lower() for a in s.desktop_apps}
        if not window or window.pid == os.getpid() or window.app.lower() not in allowed:
            return
        # Switching windows is an event; a title change is not, since terminals show each
        # running command in theirs. Text events carry the title of the moment.
        if window.hwnd != self._current:
            self._current = window.hwnd
            self._ingest(self._event("desktop_window", window))
        text, method = self._read(window)
        if text is None:
            return
        lines = screen_lines(text)
        added = new_lines(self._seen.get(window.hwnd, []), lines)
        self._seen[window.hwnd] = lines
        if added:
            self._ingest(self._event("desktop_text", window, method=method, text="\n".join(added)[:MAX_TEXT]))
