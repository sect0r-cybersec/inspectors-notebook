import io
import os
import queue
import struct
import subprocess
import sys
import threading
import uuid

import pytest

from inspectors_notebook import relay


def test_message_round_trip():
    buf = io.BytesIO()
    relay.write_message(buf, {"type": "tabs", "count": 3})
    buf.seek(0)
    assert buf.read(4) == struct.pack("<I", len(b'{"type":"tabs","count":3}'))
    buf.seek(0)
    assert relay.read_message(buf) == {"type": "tabs", "count": 3}
    assert relay.read_message(buf) is None


def test_truncated_message_is_end_of_stream():
    assert relay.read_message(io.BytesIO(struct.pack("<I", 10) + b"{}")) is None
    assert relay.read_message(io.BytesIO(b"\x01\x00")) is None


def test_oversized_messages_are_refused():
    with pytest.raises(ValueError):
        relay.read_message(io.BytesIO(struct.pack("<I", relay.MAX_FROM_BROWSER + 1)))
    with pytest.raises(ValueError):
        relay.write_message(io.BytesIO(), {"text": "x" * relay.MAX_TO_BROWSER})


if sys.platform != "win32":
    pytest.skip("Windows only", allow_module_level=True)

from inspectors_notebook import pipe  # noqa: E402


class Browser:
    """The browser's side of the relay's stdin and stdout."""

    def __init__(self):
        r, self._w = os.pipe()
        self._r_out, w_out = os.pipe()
        self.relay_in = os.fdopen(r, "rb")
        self.relay_out = os.fdopen(w_out, "wb")
        self._to_relay = os.fdopen(self._w, "wb")
        self._from_relay = os.fdopen(self._r_out, "rb")
        self.received: queue.Queue = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while (m := relay.read_message(self._from_relay)) is not None:
            self.received.put(m)

    def send(self, message):
        relay.write_message(self._to_relay, message)

    def next(self, timeout=3):
        return self.received.get(timeout=timeout)

    def close(self):
        self._to_relay.close()


class Companion:
    """A pipe server standing in for the companion; records what it receives."""

    def __init__(self, name):
        self.server = pipe.Server(name)
        self.server.listen()
        self.received: queue.Queue = queue.Queue()
        self.conns = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while (conn := self.server.accept()) is not None:
            self.conns.append(conn)
            threading.Thread(target=self._read, args=(conn,), daemon=True).start()

    def _read(self, conn):
        try:
            while True:
                self.received.put(conn.receive())
        except pipe.PipeError:
            pass

    def next(self, timeout=3):
        return self.received.get(timeout=timeout)

    def stop(self):
        self.server.close()
        for c in self.conns:
            c.close()


@pytest.fixture
def name():
    return rf"\\.\pipe\InspectorsNotebook.test.{uuid.uuid4()}"


@pytest.fixture
def browser():
    b = Browser()
    yield b
    b.close()


def start_relay(browser, name, launch=lambda: None):
    r = relay.Relay(
        browser.relay_in, browser.relay_out, lambda: pipe.connect(name), launch, poll_interval=0.1, launch_timeout=2
    )
    t = threading.Thread(target=r.run, daemon=True)
    t.start()
    return t


def test_reports_app_closed_and_drops_capture_while_closed(browser, name):
    start_relay(browser, name)
    browser.send({"type": "hello", "browser": "chrome"})
    assert browser.next() == {"type": "status", "app": "closed"}
    browser.send({"type": "event", "kind": "page_visit", "url": "https://security.microsoft.com/"})
    browser.send({"type": "tabs", "count": 2})

    companion = Companion(name)
    try:
        assert browser.next() == {"type": "status", "app": "connected"}
        # Only the hello is replayed; nothing captured while closed was kept.
        assert companion.next() == {"type": "hello", "browser": "chrome"}
        with pytest.raises(queue.Empty):
            companion.next(timeout=0.5)
    finally:
        companion.stop()


def test_round_trip_when_connected(browser, name):
    companion = Companion(name)
    try:
        start_relay(browser, name)
        assert browser.next() == {"type": "status", "app": "connected"}
        browser.send({"type": "tabs", "count": 3})
        assert companion.next() == {"type": "tabs", "count": 3}
        companion.conns[0].send({"type": "status", "recording": False})
        assert browser.next() == {"type": "status", "recording": False}
    finally:
        companion.stop()


def test_unknown_types_are_not_forwarded(browser, name):
    companion = Companion(name)
    try:
        start_relay(browser, name)
        assert browser.next()["app"] == "connected"
        browser.send({"type": "show"})
        browser.send({"type": "shell", "cmd": "calc"})
        browser.send({"type": "tabs", "count": 1})
        assert companion.next() == {"type": "tabs", "count": 1}
    finally:
        companion.stop()


def test_screenshot_requests_are_forwarded_when_connected(browser, name):
    companion = Companion(name)
    try:
        start_relay(browser, name)
        assert browser.next()["app"] == "connected"
        request = {"type": "screenshot_request", "source": "s1", "tabId": 3, "title": "Incidents", "trigger": "results"}
        browser.send(request)
        assert companion.next() == request
    finally:
        companion.stop()


def test_reconnects_after_companion_restarts(browser, name):
    companion = Companion(name)
    start_relay(browser, name)
    browser.send({"type": "hello", "browser": "edge"})
    assert browser.next()["app"] == "connected"
    companion.stop()
    assert browser.next() == {"type": "status", "app": "closed"}

    companion = Companion(name)
    try:
        assert browser.next() == {"type": "status", "app": "connected"}
        assert companion.next() == {"type": "hello", "browser": "edge"}
    finally:
        companion.stop()


def test_open_app_starts_companion_once(browser, name):
    started = []

    def launch():
        started.append(Companion(name))

    start_relay(browser, name, launch)
    assert browser.next()["app"] == "closed"
    browser.send({"type": "open_app"})
    browser.send({"type": "open_app"})
    try:
        assert browser.next() == {"type": "status", "app": "connected"}
        assert len(started) == 1
    finally:
        for c in started:
            c.stop()


def test_open_app_when_running_asks_companion_to_show(browser, name):
    companion = Companion(name)
    try:
        start_relay(browser, name, launch=lambda: pytest.fail("must not launch a second app"))
        assert browser.next()["app"] == "connected"
        browser.send({"type": "open_app"})
        assert companion.next() == {"type": "show"}
    finally:
        companion.stop()


def test_relay_exits_when_browser_disconnects(browser, name):
    t = start_relay(browser, name)
    assert browser.next()["app"] == "closed"
    browser.close()
    t.join(3)
    assert not t.is_alive()


def test_relay_process_speaks_native_messaging():
    """The real entry point, as the browser runs it. The companion is not running here."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "inspectors_notebook.relay"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )  # fmt: skip
    try:
        message = relay.read_message(proc.stdout)
        if message == {"type": "status", "app": "connected"}:
            pytest.skip("The companion is running on this machine")
        assert message == {"type": "status", "app": "closed"}
    finally:
        proc.stdin.close()
        assert proc.wait(timeout=5) == 0
