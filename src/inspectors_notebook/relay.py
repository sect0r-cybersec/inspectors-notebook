"""The relay: a native messaging host the browser starts for the listener extension.

It forwards messages between the extension (stdin and stdout, length-prefixed JSON)
and the companion (the user-only named pipe). It reports whether the companion is
running, starts it on request, and drops capture messages while it is closed, so
nothing is captured or buffered without the app (FR-35, FR-37).

stdout carries the protocol, so this module must never print.
"""

import json
import logging
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import BinaryIO, Callable

from . import pipe

log = logging.getLogger(__name__)

HOST_NAME = "inspectors_notebook.relay"
MAX_TO_BROWSER = 1024 * 1024  # Chrome's limit for host-to-extension messages
MAX_FROM_BROWSER = 64 * 1024 * 1024
FORWARDED = {"hello", "tabs", "event", "screenshot_request"}  # extension message types the companion accepts


def read_message(stream: BinaryIO) -> dict | None:
    """One native message, or None at end of stream."""
    header = stream.read(4)
    if len(header) < 4:
        return None
    (length,) = struct.unpack("<I", header)
    if length > MAX_FROM_BROWSER:
        raise ValueError(f"Message of {length} bytes is over the limit")
    body = stream.read(length)
    if len(body) < length:
        return None
    return json.loads(body.decode("utf-8"))


def write_message(stream: BinaryIO, message: dict) -> None:
    data = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_TO_BROWSER:
        raise ValueError(f"Message of {len(data)} bytes is over the browser's limit")
    stream.write(struct.pack("<I", len(data)) + data)
    stream.flush()


class Relay:
    def __init__(
        self,
        browser_in: BinaryIO,
        browser_out: BinaryIO,
        connect: Callable[[], pipe.Connection],
        launch_app: Callable[[], None],
        poll_interval: float = 1.0,
        launch_timeout: float = 15.0,
    ):
        self._in = browser_in
        self._out = browser_out
        self._connect = connect
        self._launch_app = launch_app
        self._poll = poll_interval
        self._launch_timeout = launch_timeout
        self._out_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopped = False
        self._conn: pipe.Connection | None = None
        self._app_status: str | None = None
        self._hello: dict | None = None
        self._launched_at = -1e9

    def run(self) -> None:
        threading.Thread(target=self._read_browser, name="browser", daemon=True).start()
        while not self._stopped:
            if self._conn is None:
                self._try_connect()
            launching = time.monotonic() - self._launched_at < self._launch_timeout
            self._wake.wait(0.2 if launching and self._conn is None else self._poll)
            self._wake.clear()
        with self._lock:
            if self._conn:
                self._conn.close()

    # Browser side

    def _to_browser(self, message: dict) -> None:
        with self._out_lock:
            write_message(self._out, message)

    def _set_app_status(self, status: str) -> None:
        with self._status_lock:
            if status != self._app_status:
                self._app_status = status
                self._to_browser({"type": "status", "app": status})

    def _read_browser(self) -> None:
        try:
            while (message := read_message(self._in)) is not None:
                self._from_browser(message)
        except (OSError, ValueError) as e:
            log.warning("Stopped reading from the browser: %s", e)
        self._stopped = True
        self._wake.set()

    def _from_browser(self, message: dict) -> None:
        kind = message.get("type") if isinstance(message, dict) else None
        if kind == "hello":
            self._hello = message
        if kind == "open_app":
            if self._conn:
                self._to_companion({"type": "show"})
            elif time.monotonic() - self._launched_at >= self._launch_timeout:
                log.info("Starting the companion")
                self._launched_at = time.monotonic()
                self._launch_app()
                self._wake.set()
            return
        if kind in FORWARDED:
            self._to_companion(message)  # dropped while the app is closed (FR-35)
        else:
            log.warning("Ignoring message of type %r", kind)

    # Companion side

    def _try_connect(self) -> None:
        try:
            conn = self._connect()
        except pipe.PipeError:
            self._set_app_status("closed")
            return
        with self._lock:
            self._conn = conn
        if self._hello:
            self._to_companion(self._hello)
        self._set_app_status("connected")
        threading.Thread(target=self._read_companion, args=(conn,), name="companion", daemon=True).start()

    def _to_companion(self, message: dict) -> None:
        with self._lock:
            conn = self._conn
        if conn is None:
            return
        try:
            conn.send(message)
        except pipe.PipeError:
            self._lost(conn)

    def _read_companion(self, conn: pipe.Connection) -> None:
        try:
            while True:
                self._to_browser(conn.receive())
        except pipe.PipeError:
            self._lost(conn)
        except (OSError, ValueError) as e:
            log.warning("Stopped relaying to the browser: %s", e)
            self._stopped = True
            self._wake.set()

    def _lost(self, conn: pipe.Connection) -> None:
        with self._lock:
            if self._conn is not conn:
                return
            self._conn = None
        conn.close()
        if not self._stopped:
            self._set_app_status("closed")
        self._wake.set()


def launch_companion() -> None:
    """Start the companion without a console window, outside the browser's job object."""
    scripts = Path(sys.executable).parent
    cmd = [str(scripts / "pythonw.exe"), "-m", "inspectors_notebook"]
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        # Browsers may run the host in a job that is killed when the browser closes.
        subprocess.Popen(cmd, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, close_fds=True)
    except OSError:
        subprocess.Popen(cmd, creationflags=flags, close_fds=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="relay %(levelname)s: %(message)s")
    name = pipe.default_pipe_name()
    Relay(sys.stdin.buffer, sys.stdout.buffer, lambda: pipe.connect(name), launch_companion).run()


if __name__ == "__main__":
    main()
