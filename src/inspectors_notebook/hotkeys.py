"""Global shortcuts (FR-1, FR-25, FR-53; Ctrl+Alt per docs/decisions.md).

    Ctrl+Alt+N  add a note
    Ctrl+Alt+S  start a case, or pause and resume the running one
    Ctrl+Alt+I  show or collapse the panel

Registered on a thread of their own, whose message loop receives WM_HOTKEY. A
combination another program already holds is reported, not silently lost.
"""

import ctypes
import logging
import threading
from ctypes import wintypes
from typing import Callable

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32")

MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

SHORTCUTS = {1: ("note", "N"), 2: ("record", "S"), 3: ("panel", "I")}

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def label(name: str) -> str:
    return next(f"Ctrl+Alt+{key}" for _, (n, key) in SHORTCUTS.items() if n == name)


class Hotkeys:
    def __init__(self, handlers: dict[str, Callable[[], None]]):
        self._handlers = handlers
        self._thread_id = 0
        self._ready = threading.Event()
        self.unavailable: list[str] = []  # shortcuts another program holds

    def start(self) -> list[str]:
        threading.Thread(target=self._run, name="hotkeys", daemon=True).start()
        self._ready.wait(5)
        return self.unavailable

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        registered = []
        for hotkey_id, (name, key) in SHORTCUTS.items():
            if user32.RegisterHotKey(None, hotkey_id, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord(key)):
                registered.append(hotkey_id)
            else:
                self.unavailable.append(name)
                log.warning("%s is held by another program; that shortcut is off", label(name))
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in SHORTCUTS:
                name = SHORTCUTS[msg.wParam][0]
                try:
                    self._handlers[name]()
                except Exception:
                    log.exception("Shortcut %s failed", label(name))
        for hotkey_id in registered:
            user32.UnregisterHotKey(None, hotkey_id)
