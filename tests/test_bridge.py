import sys
import threading
import time
import uuid

import pytest

if sys.platform != "win32":
    pytest.skip("Windows only", allow_module_level=True)

from inspectors_notebook import pipe
from inspectors_notebook.bridge import MAX_TABS, Bridge
from inspectors_notebook.case_store import CaseStore
from inspectors_notebook.cases import CaseManager
from inspectors_notebook.screenshot import Shot


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class FakeShooter:
    """Captures nothing; returns a shot unless the title says the window is unchanged."""

    def __init__(self):
        self.calls = []

    def capture(self, browser, tab_key, title):
        self.calls.append((browser, tab_key, title))
        return None if title == "unchanged" else Shot(b"RIFF....WEBP", 10, 10)


@pytest.fixture
def setup(tmp_path):
    name = rf"\\.\pipe\InspectorsNotebook.test.{uuid.uuid4()}"
    server = pipe.Server(name)
    server.listen()
    updates, shows = [], []
    cases = CaseManager(CaseStore(tmp_path / "cases"))
    bridge = Bridge(server, updates.append, lambda: shows.append(True), FakeShooter(), cases)
    bridge.start()
    clients = []

    def client():
        c = pipe.connect(name, timeout_ms=2000)
        clients.append(c)
        return c

    yield bridge, client, updates, shows
    for c in clients:
        c.close()
    bridge.stop()


def test_hello_is_answered_and_counted(setup):
    bridge, client, updates, _ = setup
    c = client()
    c.send({"type": "hello", "browser": "chrome"})
    assert c.receive() == {"type": "status", "recording": False}
    assert wait_for(lambda: bridge.listener() == {"browsers": 1, "tabs": 0})


def test_tabs_are_summed_across_browsers(setup):
    bridge, client, updates, _ = setup
    for browser, tabs in [("chrome", 2), ("edge", 1), ("firefox", 4)]:
        c = client()
        c.send({"type": "hello", "browser": browser})
        c.receive()
        c.send({"type": "tabs", "count": tabs})
    assert wait_for(lambda: bridge.listener() == {"browsers": 3, "tabs": 7})
    assert updates[-1] == {"browsers": 3, "tabs": 7}


def test_disconnect_removes_browser(setup):
    bridge, client, updates, _ = setup
    c = client()
    c.send({"type": "hello", "browser": "edge"})
    c.receive()
    c.send({"type": "tabs", "count": 3})
    assert wait_for(lambda: bridge.listener()["tabs"] == 3)
    c.close()
    assert wait_for(lambda: bridge.listener() == {"browsers": 0, "tabs": 0})
    assert updates[-1] == {"browsers": 0, "tabs": 0}


def test_show_request_and_non_browser_clients(setup):
    bridge, client, _, shows = setup
    c = client()
    c.send({"type": "show"})
    assert wait_for(lambda: shows == [True])
    assert bridge.listener() == {"browsers": 0, "tabs": 0}


def test_bad_counts_are_ignored_or_clamped(setup):
    bridge, client, _, _ = setup
    c = client()
    c.send({"type": "hello", "browser": "chrome"})
    c.receive()
    c.send({"type": "tabs", "count": "7"})
    c.send({"type": "tabs", "count": True})
    c.send({"type": "tabs", "count": 10**9})
    assert wait_for(lambda: bridge.listener()["tabs"] == MAX_TABS)
    c.send({"type": "tabs", "count": -5})
    assert wait_for(lambda: bridge.listener()["tabs"] == 0)


def test_events_are_counted_not_kept(setup):
    bridge, client, _, _ = setup
    c = client()
    c.send({"type": "hello", "browser": "chrome"})
    c.receive()
    for _ in range(3):
        c.send({"type": "event", "kind": "page_visit", "url": "https://security.microsoft.com/"})
    assert wait_for(lambda: bridge.events_received == 3)
    held = [k for k, v in vars(bridge).items() if k != "_clients" and isinstance(v, (list, dict, tuple)) and v]
    assert held == []
    assert "security.microsoft.com" not in repr(bridge._clients)


def test_screenshots_are_captured_into_the_case_only_while_recording(setup):
    bridge, client, _, _ = setup
    c = client()
    c.send({"type": "hello", "browser": "edge"})
    c.receive()
    request = {"type": "screenshot_request", "source": "s1", "tabId": 7, "title": "Incidents", "trigger": "navigation"}
    c.send(request)
    assert wait_for(lambda: bridge.screenshots_skipped == 1)
    assert bridge._shooter.calls == []  # nothing captured without a case

    bridge._cases.start(title="Lab case")
    c.send(request)
    c.send({**request, "title": "unchanged", "trigger": "tab_switch"})
    assert wait_for(lambda: (bridge.screenshots_taken, bridge.screenshots_skipped) == (1, 2))
    assert bridge._shooter.calls == [("edge", ("s1", 7), "Incidents"), ("edge", ("s1", 7), "unchanged")]
    shot = bridge._cases.events()[0][0]
    assert (shot["kind"], shot["trigger"], shot["file"]) == ("screenshot", "navigation", "screenshots/000001.webp")


def test_browsers_hear_when_recording_starts_and_stops(setup):
    bridge, client, _, _ = setup
    c = client()
    c.send({"type": "hello", "browser": "chrome"})
    assert c.receive() == {"type": "status", "recording": False}
    bridge.set_recording(True)
    assert c.receive() == {"type": "status", "recording": True}
    bridge.set_recording(True)  # no change, no message
    bridge.set_recording(False)
    assert c.receive() == {"type": "status", "recording": False}


def test_capture_events_go_to_the_case(setup):
    bridge, client, _, _ = setup
    bridge._cases.start(entities=["HOST-12"])
    c = client()
    c.send({"type": "hello", "browser": "chrome"})
    assert c.receive() == {"type": "status", "recording": True}
    c.send({"type": "event", "kind": "query", "query": "DeviceInfo | where DeviceName == 'HOST-12'"})
    assert wait_for(lambda: len(bridge._cases.events()) == 1)
    assert bridge._cases.events()[0][1].reason == "entity"


def test_one_client_failing_leaves_others_working(setup):
    bridge, client, _, _ = setup
    good, bad = client(), client()
    good.send({"type": "hello", "browser": "chrome"})
    good.receive()
    bad.send({"type": "hello", "browser": "edge"})
    bad.receive()
    bad.close()
    assert wait_for(lambda: bridge.listener()["browsers"] == 1)
    good.send({"type": "tabs", "count": 2})
    assert wait_for(lambda: bridge.listener()["tabs"] == 2)
