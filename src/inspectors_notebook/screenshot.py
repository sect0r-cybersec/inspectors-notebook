"""Screenshots of the browser window a console tab is showing (FR-13).

Browsers only let an extension capture tabs if it may read every website, so the
extension asks and the companion captures the window itself: it finds the browser's
top-level window by class and title, renders it with PrintWindow (which works when it
is partly covered), and saves WebP (NFR-4). A screenshot is skipped when the window
has not visibly changed since the last one for the same tab.
"""

import ctypes
import io
from ctypes import wintypes
from dataclasses import dataclass

from PIL import Image

from . import win32

WINDOW_CLASSES = {
    "chrome": "Chrome_WidgetWin_1",
    "edge": "Chrome_WidgetWin_1",
    "firefox": "MozillaWindowClass",
}
THUMB_SIZE = (32, 18)
CHANGE_THRESHOLD = 2  # mean difference per thumbnail pixel, 0 to 255
WEBP_QUALITY = 80

PW_RENDERFULLCONTENT = 0x2
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DIB_RGB_COLORS = 0
BI_RGB = 0

user32 = win32.user32
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


gdi32.GetDIBits.argtypes = [
    wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, wintypes.LPVOID,
    ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
]  # fmt: skip


def _text(fn, hwnd: int, size: int) -> str:
    buf = ctypes.create_unicode_buffer(size)
    fn(hwnd, buf, size)
    return buf.value


def find_window(browser: str, tab_title: str) -> int | None:
    """The topmost visible browser window whose title starts with the tab's title.

    Browsers title their windows after the active tab, then add the browser name
    (and in Edge, the profile and tab count).
    """
    wanted = WINDOW_CLASSES.get(browser)
    if not wanted or not tab_title:
        return None
    found: list[int] = []

    def visit(hwnd, _):
        if (
            user32.IsWindowVisible(hwnd)
            and not user32.IsIconic(hwnd)
            and _text(user32.GetClassNameW, hwnd, 256) == wanted
            and _text(user32.GetWindowTextW, hwnd, user32.GetWindowTextLengthW(hwnd) + 1).startswith(tab_title)
        ):
            found.append(hwnd)
            return False  # windows are enumerated top-down, so the first match is topmost
        return True

    user32.EnumWindows(WNDENUMPROC(visit), 0)
    return found[0] if found else None


def capture_window(hwnd: int) -> Image.Image:
    """Render a window into an image, including content the GPU composes."""
    rect = win32.window_rect(hwnd)
    width, height = rect.width, rect.height
    if width <= 0 or height <= 0:
        raise OSError("The window has no area")
    screen = user32.GetDC(None)
    dc = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
    old = gdi32.SelectObject(dc, bitmap)
    try:
        if not user32.PrintWindow(hwnd, dc, PW_RENDERFULLCONTENT):
            raise ctypes.WinError(ctypes.get_last_error())
        header = BITMAPINFOHEADER(
            biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=width, biHeight=-height,  # top-down rows
            biPlanes=1, biBitCount=32, biCompression=BI_RGB,
        )  # fmt: skip
        pixels = ctypes.create_string_buffer(width * height * 4)
        if not gdi32.GetDIBits(dc, bitmap, 0, height, pixels, ctypes.byref(header), DIB_RGB_COLORS):
            raise OSError("GetDIBits failed")
    finally:
        gdi32.SelectObject(dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(dc)
        user32.ReleaseDC(None, screen)
    image = Image.frombuffer("RGB", (width, height), pixels.raw, "raw", "BGRX", 0, 1)
    # The window rect includes invisible resize borders; keep only the visible frame.
    frame = win32.RECT()
    try:
        win32.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(frame), ctypes.sizeof(frame))
    except OSError:
        return image  # no DWM frame information: keep the full window rect
    box = (frame.left - rect.left, frame.top - rect.top, frame.right - rect.left, frame.bottom - rect.top)
    if 0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height:
        image = image.crop(box)
    return image


def thumbnail(image: Image.Image) -> bytes:
    return image.convert("L").resize(THUMB_SIZE, Image.Resampling.BOX).tobytes()


def changed(previous: bytes | None, current: bytes) -> bool:
    """Whether the window visibly changed. A blinking caret or ticking clock does not count."""
    if previous is None or len(previous) != len(current):
        return True
    return sum(abs(a - b) for a, b in zip(previous, current)) / len(current) > CHANGE_THRESHOLD


def encode_webp(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "WEBP", quality=WEBP_QUALITY)
    return out.getvalue()


@dataclass
class Shot:
    webp: bytes
    width: int
    height: int


class Screenshotter:
    """Captures on request and skips windows that have not changed, per tab."""

    def __init__(self) -> None:
        self._last: dict[tuple, bytes] = {}

    def capture(self, browser: str, tab_key: tuple, tab_title: str) -> Shot | None:
        hwnd = find_window(browser, tab_title)
        if hwnd is None:
            return None
        image = capture_window(hwnd)
        thumb = thumbnail(image)
        if not changed(self._last.get(tab_key), thumb):
            return None
        self._last[tab_key] = thumb
        return Shot(encode_webp(image), image.width, image.height)
