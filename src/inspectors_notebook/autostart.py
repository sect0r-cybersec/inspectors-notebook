"""Start Inspector when Windows starts (FR-38): an entry in the user's Run key.

Per user, so no admin rights. The command starts the companion without a console
window: the installed executable, or pythonw when run from source.
"""

import subprocess
import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "InspectorsNotebook"
APP_EXE = "inspectors-notebook.exe"  # beside the relay in the installed folder


def companion_command(executable: str = sys.executable, frozen: bool = getattr(sys, "frozen", False)) -> list[str]:
    if frozen:
        return [str(Path(executable).with_name(APP_EXE))]
    return [str(Path(executable).with_name("pythonw.exe")), "-m", "inspectors_notebook"]


def command() -> str:
    return subprocess.list2cmdline(companion_command())


def is_enabled(key_path: str = RUN_KEY) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.QueryValueEx(key, VALUE)
            return True
    except FileNotFoundError:
        return False


def set_enabled(enabled: bool, key_path: str = RUN_KEY) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, VALUE)
            except FileNotFoundError:
                pass
