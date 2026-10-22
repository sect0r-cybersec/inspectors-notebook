"""The built installer, end to end: install for this user, run, upgrade over itself, uninstall.

    powershell -ExecutionPolicy Bypass -File packaging/build.ps1
    uv run pytest -m installer

Installs into a temporary folder. The browser registration and the Start with Windows entry
are this user's real ones, so they are saved first and put back afterwards. Close Inspector
before running: one companion runs per user.
"""

import ctypes
import json
import os
import queue
import subprocess
import threading
import time
import tomllib
import winreg
from pathlib import Path
from urllib.parse import urlsplit

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


def has_visible_window(pid: int) -> bool:
    found = []
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(hwnd, _):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
            found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(visit), 0)
    return bool(found)


def wait_for_panel(pid: int, timeout: float = 60) -> bool:
    """The companion answers its pipe before its window is up; the panel follows once docked."""
    deadline = time.monotonic() + timeout
    while not has_visible_window(pid) and time.monotonic() < deadline:
        time.sleep(0.5)
    return has_visible_window(pid)


def stop_apps(target: Path) -> list[int]:
    """Closes the installed app as the user would, then forces any that would not close, so a
    failing test doesn't leave it running into the next one. Returns those that had to be forced."""
    for pid in app_processes(target):
        close_app(pid)
    left = app_processes(target)
    for pid in left:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    return left


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
        assert wait_for_panel(pid), "the panel did not appear"
    finally:
        try:
            assert browser.close() == 0
        finally:
            forced = stop_apps(installed)
    assert forced == []


def test_a_second_launch_brings_the_first_forward(installed):
    first = subprocess.Popen([str(installed / "inspectors-notebook.exe")])
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            pipe.connect(pipe.default_pipe_name(), timeout_ms=500).close()
            break
        except pipe.PipeError:
            time.sleep(0.5)
    try:
        # Usually while the first is still starting: it answers the pipe before its window is up.
        second = subprocess.run([str(installed / "inspectors-notebook.exe")], timeout=30)
        assert second.returncode == 0 and first.poll() is None
        assert wait_for_panel(first.pid), "the panel did not appear"
        close_app(first.pid)
        assert first.wait(timeout=5) == 0
    finally:
        stop_apps(installed)


# NFR-1. WebView2, the engine that draws the panel, contacts Microsoft on its own: remote
# configuration, component updates, and the proxy lookup Windows' "Automatically detect
# settings" asks for. Inspector can't turn these off with a supported setting
# (docs/decisions.md), so they are allowed by name and anything else fails.
WEBVIEW2_HOSTS = {
    "config.edge.skype.com",  # Edge remote configuration and experiments
    "edge.microsoft.com",  # component updater
    "msedge.b.tlu.dl.delivery.mp.microsoft.com",  # component downloads
    "wpad",  # proxy auto-discovery, on the local network
}
WATCH_SECONDS = 120  # component updates started about 60 s after launch


def process_tree(root: int) -> dict[int, str]:
    script = 'Get-CimInstance Win32_Process | ForEach-Object { "$($_.ProcessId)|$($_.ParentProcessId)|$($_.Name)" }'
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True).stdout
    rows = [line.split("|", 2) for line in out.splitlines() if line.count("|") >= 2]
    names = {int(pid): name for pid, _, name in rows}
    children: dict[int, list[int]] = {}
    for pid, parent, _ in rows:
        children.setdefault(int(parent), []).append(int(pid))
    found, todo = {}, [root]
    while todo:
        pid = todo.pop()
        if pid in names and pid not in found:
            found[pid] = names[pid]
            todo += children.get(pid, [])
    return found


def socket_endpoints() -> list[tuple[str, str, str, str, int]]:
    """Every TCP and UDP endpoint on the machine: (protocol, local, remote, state, pid)."""
    rows = []
    for line in subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout.splitlines():
        parts = line.split()
        if parts[:1] == ["TCP"] and len(parts) == 5:
            rows.append(("TCP", parts[1], parts[2], parts[3], int(parts[4])))
        elif parts[:1] == ["UDP"] and len(parts) == 4:
            rows.append(("UDP", parts[1], parts[2], "", int(parts[3])))
    return rows


def net_log_hosts(path: Path) -> tuple[int, set[str]]:
    """Events in WebView2's network log, and every host they name."""
    text = path.read_text(encoding="utf-8").rstrip()
    if not text.endswith("}"):  # still being written when read
        text = text.rstrip(",") + "]}"
    events = json.loads(text)["events"]
    hosts = set()
    for event in events:
        params = event.get("params") or {}
        for key in ("url", "original_url", "host", "server_hostname", "hostname"):
            value = params.get(key)
            if isinstance(value, str) and value:
                hosts.add(urlsplit(value if "://" in value else f"//{value}").hostname or value)
    return len(events), hosts


def test_nothing_but_webview2_housekeeping_reaches_the_network(installed, tmp_path):
    net_log = tmp_path / "netlog.json"
    # Test only: WebView2's own network log, through its documented environment variable.
    env = {**os.environ, "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": f"--log-net-log={net_log} --net-log-capture-mode=Default"}
    app = subprocess.Popen([str(installed / "inspectors-notebook.exe")], env=env)
    own, listening = set(), set()
    try:
        assert wait_for_panel(app.pid), "the panel did not appear"
        browser = pipe.connect(pipe.default_pipe_name(), timeout_ms=5000)
        browser.send({"type": "hello", "browser": "chrome"})
        browser.send({"type": "tabs", "count": 2})
        tree, refreshed = {}, 0.0
        deadline = time.monotonic() + WATCH_SECONDS
        while time.monotonic() < deadline:
            if time.monotonic() - refreshed > 5:
                tree, refreshed = process_tree(app.pid), time.monotonic()
            for proto, local, remote, state, pid in socket_endpoints():
                if pid == app.pid:
                    own.add((proto, local, remote, state))
                elif pid in tree and state == "LISTENING":
                    listening.add((tree[pid], local))
            time.sleep(1)
        browser.close()
        close_app(app.pid)
    finally:
        stop_apps(installed)
    assert own == set(), "Inspector's own process opened network endpoints"
    assert listening == set(), "something in the app listens on a port (NFR-5)"
    events, hosts = net_log_hosts(net_log)
    assert events > 0, "WebView2 wrote no network log; the check would prove nothing"
    assert hosts <= WEBVIEW2_HOSTS, f"unexpected hosts: {sorted(hosts - WEBVIEW2_HOSTS)}"


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
