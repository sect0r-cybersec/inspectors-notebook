"""The built installer, end to end: install for this user, run, upgrade over itself, uninstall.

    powershell -ExecutionPolicy Bypass -File packaging/build.ps1
    uv run pytest -m installer

Installs into a temporary folder. The browser registration and the Start with Windows entry
are this user's real ones, so they are saved first and put back afterwards. Close Inspector
before running: one companion runs per user.
"""

import json
import queue
import subprocess
import threading
import time
import tomllib
import winreg
from pathlib import Path

import pytest

from inspectors_notebook import autostart, case_store, pipe, register, relay

pytestmark = pytest.mark.installer

ROOT = Path(__file__).parent.parent
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
SETUP = ROOT / "dist" / f"InspectorsNotebook-{VERSION}-setup.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{6C1F3E0A-8D52-4B7E-9A64-2F0D5C9B7E31}_is1"
PROGRAMS = ["inspectors-notebook.exe", "inspectors-notebook-relay.exe", "inspectors-notebook-register.exe"]


def read_value(key: str, name: str = "") -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return winreg.QueryValueEx(k, name)[0]
    except FileNotFoundError:
        return None


def key_exists(key: str) -> bool:
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, key).Close()
        return True
    except FileNotFoundError:
        return False


def browser_keys() -> list[str]:
    return [rf"{key}\{relay.HOST_NAME}" for key, _ in register.BROWSERS.values()]


def manifest_files() -> list[Path]:
    return [register.default_folder() / f"{relay.HOST_NAME}.{f}.json" for f in ("chromium", "firefox")]


@pytest.fixture(scope="module")
def saved_registration():
    """This user's relay registration and Start with Windows entry, restored afterwards."""
    values = {key: read_value(key) for key in browser_keys()}
    files = {path: path.read_bytes() if path.exists() else None for path in manifest_files()}
    run = read_value(autostart.RUN_KEY, autostart.VALUE)
    yield
    registry = register.UserRegistry()
    for key, value in values.items():
        registry.set_default(key, value) if value is not None else registry.delete(key)
    for path, content in files.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, autostart.RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if run is not None:
            winreg.SetValueEx(k, autostart.VALUE, 0, winreg.REG_SZ, run)
        else:
            try:
                winreg.DeleteValue(k, autostart.VALUE)
            except FileNotFoundError:
                pass


def run_setup(target: Path, log: Path) -> None:
    args = [str(SETUP), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/DIR={target}", f"/LOG={log}"]
    result = subprocess.run(args, timeout=300)
    assert result.returncode == 0, log.read_text(encoding="utf-8", errors="replace")


def run_uninstaller(target: Path) -> None:
    args = [str(target / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
    assert subprocess.run(args, timeout=120).returncode == 0
    # The uninstaller hands over to a copy of itself in %TEMP% and returns at once.
    deadline = time.monotonic() + 120
    while target.exists() and time.monotonic() < deadline:
        time.sleep(0.5)


@pytest.fixture(scope="module")
def installed(saved_registration, tmp_path_factory):
    if not SETUP.is_file():
        pytest.fail(f"{SETUP.name} is not built: run packaging/build.ps1 first")
    try:
        pipe.connect(pipe.default_pipe_name(), timeout_ms=200).close()
        pytest.fail("Inspector is running: close it first")
    except pipe.PipeError:
        pass
    # A space and an apostrophe, to catch quoting mistakes in the paths the installer writes.
    target = tmp_path_factory.mktemp("install") / "Inspector's Notebook"
    run_setup(target, target.parent / "install.log")
    yield target
    if (target / "unins000.exe").exists():
        for pid in app_processes(target):
            close_app(pid)
        run_uninstaller(target)


def app_processes(target: Path) -> list[int]:
    script = 'Get-Process inspectors-notebook -ErrorAction SilentlyContinue | ForEach-Object { "$($_.Id)|$($_.Path)" }'
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True).stdout
    found = [line.split("|", 1) for line in out.splitlines() if "|" in line]
    return [int(pid) for pid, path in found if Path(path).parent == target]


def close_app(pid: int, timeout: float = 20) -> None:
    """Closes the panel's window the way the user would, and waits for the process to end."""
    script = f"(Get-Process -Id {pid}).CloseMainWindow() | Out-Null; Wait-Process -Id {pid} -Timeout {int(timeout)}"
    subprocess.run(["powershell", "-NoProfile", "-Command", script], timeout=timeout + 10)


class RelayProcess:
    """The installed relay, started the way a browser starts it."""

    def __init__(self, exe: Path):
        self.proc = subprocess.Popen([str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.received: queue.Queue = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while (m := relay.read_message(self.proc.stdout)) is not None:
            self.received.put(m)

    def send(self, message):
        relay.write_message(self.proc.stdin, message)
        self.proc.stdin.flush()

    def next(self, timeout=5):
        return self.received.get(timeout=timeout)

    def close(self):
        self.proc.stdin.close()
        return self.proc.wait(timeout=10)


def test_installs_the_programs_and_registers_the_relay(installed):
    for name in PROGRAMS:
        assert (installed / name).is_file()
    assert (installed / "_internal" / "inspectors_notebook" / "ui" / "panel.html").is_file()
    assert read_value(UNINSTALL_KEY, "DisplayVersion") == VERSION
    for key in browser_keys():
        manifest_path = Path(read_value(key))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["path"] == str(installed / "inspectors-notebook-relay.exe")
        assert manifest["name"] == relay.HOST_NAME


def test_the_installed_relay_starts_the_installed_app(installed):
    browser = RelayProcess(installed / "inspectors-notebook-relay.exe")
    try:
        assert browser.next() == {"type": "status", "app": "closed"}
        browser.send({"type": "hello", "browser": "chrome"})
        browser.send({"type": "open_app"})
        # A cold start loads the Python runtime, .NET and WebView2.
        assert browser.next(timeout=60) == {"type": "status", "app": "connected"}
        status = browser.next(timeout=10)
        assert status["type"] == "status" and status["recording"] is False
        [pid] = app_processes(installed)
    finally:
        assert browser.close() == 0
    close_app(pid)
    assert app_processes(installed) == []


def test_a_second_launch_brings_the_first_forward(installed):
    first = subprocess.Popen([str(installed / "inspectors-notebook.exe")])
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            pipe.connect(pipe.default_pipe_name(), timeout_ms=500).close()
            break
        except pipe.PipeError:
            time.sleep(0.5)
    second = subprocess.run([str(installed / "inspectors-notebook.exe")], timeout=30)
    assert second.returncode == 0 and first.poll() is None
    close_app(first.pid)
    assert first.wait(timeout=5) == 0


def test_upgrading_closes_the_running_app_and_keeps_the_registration(installed):
    app = subprocess.Popen([str(installed / "inspectors-notebook.exe")])
    time.sleep(10)  # running and holding its files
    run_setup(installed, installed.parent / "upgrade.log")
    app.wait(timeout=30)  # Setup closed it to replace its files
    for name in PROGRAMS:
        assert (installed / name).is_file()
    for key in browser_keys():
        assert read_value(key) is not None


def test_uninstalling_removes_the_app_but_keeps_the_cases(installed):
    cases_root = case_store.default_root()
    cases_before = sorted(p.name for p in cases_root.iterdir()) if cases_root.exists() else None
    command = subprocess.list2cmdline([str(installed / "inspectors-notebook.exe")])
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, autostart.RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, autostart.VALUE, 0, winreg.REG_SZ, command)  # Start with Windows on

    run_uninstaller(installed)

    assert not installed.exists()
    assert not key_exists(UNINSTALL_KEY)
    assert [key for key in browser_keys() if key_exists(key)] == []
    assert [path for path in manifest_files() if path.exists()] == []
    assert read_value(autostart.RUN_KEY, autostart.VALUE) is None
    cases_after = sorted(p.name for p in cases_root.iterdir()) if cases_root.exists() else None
    assert cases_after == cases_before
