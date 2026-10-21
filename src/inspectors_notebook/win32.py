"""ctypes bindings for the few Win32 calls the panel needs."""

import ctypes
import time
import winreg
from ctypes import wintypes

from .geometry import Rect

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
shcore = ctypes.WinDLL("shcore")
dwmapi = ctypes.WinDLL("dwmapi")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = wintypes.LPARAM
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

# Messages
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_DISPLAYCHANGE = 0x007E
WM_POWERBROADCAST = 0x0218
WM_APP = 0x8000
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012

# SHAppBarMessage
ABM_NEW = 0x0
ABM_REMOVE = 0x1
ABM_QUERYPOS = 0x2
ABM_SETPOS = 0x3
ABE_LEFT = 0
ABE_RIGHT = 2
ABN_POSCHANGED = 0x1
ABN_FULLSCREENAPP = 0x2

# Windows and positions
WS_POPUP = 0x80000000
WS_EX_TOOLWINDOW = 0x00000080
HWND_TOPMOST = wintypes.HWND(-1)
HWND_NOTOPMOST = wintypes.HWND(-2)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_ASYNCWINDOWPOS = 0x4000
MONITOR_DEFAULTTONEAREST = 2
MDT_EFFECTIVE_DPI = 0
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = wintypes.HANDLE(-4)

# DWM
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_ROUND = 2


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]

    def to_rect(self) -> Rect:
        return Rect(self.left, self.top, self.right, self.bottom)

    @classmethod
    def from_rect(cls, r: Rect) -> "RECT":
        return cls(r.left, r.top, r.right, r.bottom)


class APPBARDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uCallbackMessage", wintypes.UINT),
        ("uEdge", wintypes.UINT),
        ("rc", RECT),
        ("lParam", wintypes.LPARAM),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


def _sig(fn, restype, *argtypes):
    fn.restype = restype
    fn.argtypes = argtypes
    return fn


SHAppBarMessage = _sig(shell32.SHAppBarMessage, ctypes.c_size_t, wintypes.DWORD, ctypes.POINTER(APPBARDATA))
RegisterClassExW = _sig(user32.RegisterClassExW, wintypes.ATOM, ctypes.POINTER(WNDCLASSEXW))
UnregisterClassW = _sig(user32.UnregisterClassW, wintypes.BOOL, wintypes.LPCWSTR, wintypes.HINSTANCE)
CreateWindowExW = _sig(
    user32.CreateWindowExW, wintypes.HWND,
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
)  # fmt: skip
DestroyWindow = _sig(user32.DestroyWindow, wintypes.BOOL, wintypes.HWND)
DefWindowProcW = _sig(user32.DefWindowProcW, LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
GetMessageW = _sig(user32.GetMessageW, wintypes.BOOL, ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
TranslateMessage = _sig(user32.TranslateMessage, wintypes.BOOL, ctypes.POINTER(wintypes.MSG))
DispatchMessageW = _sig(user32.DispatchMessageW, LRESULT, ctypes.POINTER(wintypes.MSG))
PostMessageW = _sig(user32.PostMessageW, wintypes.BOOL, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
PostQuitMessage = _sig(user32.PostQuitMessage, None, ctypes.c_int)
SetWindowPos = _sig(
    user32.SetWindowPos, wintypes.BOOL,
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT,
)  # fmt: skip
GetWindowRect = _sig(user32.GetWindowRect, wintypes.BOOL, wintypes.HWND, ctypes.POINTER(RECT))
MonitorFromWindow = _sig(user32.MonitorFromWindow, wintypes.HMONITOR, wintypes.HWND, wintypes.DWORD)
GetMonitorInfoW = _sig(user32.GetMonitorInfoW, wintypes.BOOL, wintypes.HMONITOR, ctypes.POINTER(MONITORINFO))
GetDpiForMonitor = _sig(
    shcore.GetDpiForMonitor, ctypes.HRESULT,
    wintypes.HMONITOR, ctypes.c_int, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT),
)  # fmt: skip
SetProcessDpiAwarenessContext = _sig(user32.SetProcessDpiAwarenessContext, wintypes.BOOL, wintypes.HANDLE)
DwmGetWindowAttribute = _sig(
    dwmapi.DwmGetWindowAttribute, ctypes.HRESULT, wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD
)
DwmSetWindowAttribute = _sig(
    dwmapi.DwmSetWindowAttribute, ctypes.HRESULT, wintypes.HWND, wintypes.DWORD, wintypes.LPCVOID, wintypes.DWORD
)
GetModuleHandleW = _sig(kernel32.GetModuleHandleW, wintypes.HMODULE, wintypes.LPCWSTR)


def enable_per_monitor_dpi() -> None:
    """Opt in to per-monitor DPI v2 so coordinates are physical pixels on every monitor.

    Must run before any window is created. pywebview later asks for system DPI
    awareness, which Windows ignores once this is set.
    """
    if not SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
        raise ctypes.WinError(ctypes.get_last_error())


def monitor_of(hwnd: int) -> tuple[Rect, Rect, int]:
    """Monitor rect, work area and effective DPI for the monitor nearest a window."""
    hmon = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    if not GetMonitorInfoW(hmon, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
    GetDpiForMonitor(hmon, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
    return info.rcMonitor.to_rect(), info.rcWork.to_rect(), dpi_x.value


def window_rect(hwnd: int) -> Rect:
    rc = RECT()
    if not GetWindowRect(hwnd, ctypes.byref(rc)):
        raise ctypes.WinError(ctypes.get_last_error())
    return rc.to_rect()


def colorref(hex_colour: str) -> int:
    """'#RRGGBB' to a Win32 COLORREF (0x00BBGGRR)."""
    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return r | (g << 8) | (b << 16)


def style_window_frame(hwnd: int, border_hex: str) -> None:
    """Ask DWM for rounded corners and a themed 1 px border. Windows 10 ignores both."""
    pref = ctypes.c_int(DWMWCP_ROUND)
    DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref), ctypes.sizeof(pref))
    colour = wintypes.DWORD(colorref(border_hex))
    DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(colour), ctypes.sizeof(colour))


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


GetLastInputInfo = _sig(user32.GetLastInputInfo, wintypes.BOOL, ctypes.POINTER(LASTINPUTINFO))
GetTickCount = _sig(kernel32.GetTickCount, wintypes.DWORD)


def idle_seconds() -> float:
    """Seconds since the user last pressed a key or moved the mouse."""
    info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    if not GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return ((GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000  # tick counts wrap every 49.7 days


def windows_uses_light_theme() -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        ) as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 1
    except OSError:
        return False


# Clipboard (FR-27)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
OpenClipboard = _sig(user32.OpenClipboard, wintypes.BOOL, wintypes.HWND)
CloseClipboard = _sig(user32.CloseClipboard, wintypes.BOOL)
EmptyClipboard = _sig(user32.EmptyClipboard, wintypes.BOOL)
SetClipboardData = _sig(user32.SetClipboardData, wintypes.HANDLE, wintypes.UINT, wintypes.HANDLE)
GetClipboardData = _sig(user32.GetClipboardData, wintypes.HANDLE, wintypes.UINT)
RegisterClipboardFormatW = _sig(user32.RegisterClipboardFormatW, wintypes.UINT, wintypes.LPCWSTR)
GlobalAlloc = _sig(kernel32.GlobalAlloc, wintypes.HGLOBAL, wintypes.UINT, ctypes.c_size_t)
GlobalLock = _sig(kernel32.GlobalLock, wintypes.LPVOID, wintypes.HGLOBAL)
GlobalUnlock = _sig(kernel32.GlobalUnlock, wintypes.BOOL, wintypes.HGLOBAL)


def _cf_html(fragment: str) -> bytes:
    """Windows' "HTML Format": a header of byte offsets, then the document."""
    prefix = "<html><body><!--StartFragment-->"
    suffix = "<!--EndFragment--></body></html>"
    template = "Version:0.9\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\nStartFragment:{:010d}\r\nEndFragment:{:010d}\r\n"
    header_len = len(template.format(0, 0, 0, 0).encode("ascii"))
    body = (prefix + fragment + suffix).encode("utf-8")
    start_fragment = header_len + len(prefix.encode("utf-8"))
    end_fragment = start_fragment + len(fragment.encode("utf-8"))
    header = template.format(header_len, header_len + len(body), start_fragment, end_fragment)
    return header.encode("ascii") + body


def _global(data: bytes) -> int:
    handle = GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    ctypes.memmove(GlobalLock(handle), data, len(data))
    GlobalUnlock(handle)
    return handle


def set_clipboard(text: str, html: str | None = None) -> None:
    """Put text (and optionally HTML, for rich paste) on the clipboard."""
    for _ in range(10):  # another program may hold the clipboard for a moment
        if OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        EmptyClipboard()
        SetClipboardData(CF_UNICODETEXT, _global((text + "\0").encode("utf-16-le")))
        if html is not None:
            SetClipboardData(RegisterClipboardFormatW("HTML Format"), _global(_cf_html(html) + b"\0"))
    finally:
        CloseClipboard()


def get_clipboard_text() -> str:
    if not OpenClipboard(None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        handle = GetClipboardData(CF_UNICODETEXT)
        return ctypes.wstring_at(GlobalLock(handle)) if handle else ""
    finally:
        if handle:
            GlobalUnlock(handle)
        CloseClipboard()
