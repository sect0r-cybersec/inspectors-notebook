"""The companion's end of the pipe: one relay connection per browser (FR-36).

Tracks which browsers are connected and how many console tabs they report, and tells
every browser whether a case is recording. Capture events go to the case manager.
Screenshot requests are captured on a worker thread, so the pipe keeps flowing, and
only while a case records.
"""

import logging
import queue
import threading
from typing import Callable

from . import pipe
from .cases import CaseManager
from .screenshot import Screenshotter
from .settings import Settings

log = logging.getLogger(__name__)

MAX_TABS = 10_000


class Bridge:
    def __init__(
        self,
        server: pipe.Server,
        on_listener: Callable[[dict], None],
        on_show: Callable[[], None],
        screenshotter: Screenshotter | None = None,
        cases: CaseManager | None = None,
        settings: Callable[[], Settings] = Settings,
    ):
        self._server = server
        self._on_listener = on_listener
        self._on_show = on_show
        self._lock = threading.Lock()
        self._clients: dict[int, dict] = {}
        self._next_id = 0
        self._shooter = screenshotter
        self._cases = cases
        self._settings = settings
        self._status: dict | None = None
        self._shot_requests: queue.Queue = queue.Queue(maxsize=8)
        self.events_received = 0
        self.screenshots_taken = 0
        self.screenshots_skipped = 0

    def start(self) -> None:
        threading.Thread(target=self._serve, name="bridge", daemon=True).start()
        if self._shooter:
            threading.Thread(target=self._take_screenshots, name="screenshots", daemon=True).start()

    def stop(self) -> None:
        self._server.close()
        self._shot_requests.put(None)

    def listener(self) -> dict:
        with self._lock:
            browsers = [c for c in self._clients.values() if c["browser"]]
            return {"browsers": len(browsers), "tabs": sum(c["tabs"] for c in browsers)}

    def _notify(self) -> None:
        self._on_listener(self.listener())

    def _is_recording(self) -> bool:
        return bool(self._cases and self._cases.recording)

    def _status_message(self) -> dict:
        s = self._settings()
        return {"type": "status", "recording": self._is_recording(), "screenshots": s.screenshots, "interval": s.interval_seconds}

    def update_status(self) -> None:
        """Tell every connected browser when recording or the screenshot settings change."""
        status = self._status_message()
        with self._lock:
            if status == self._status:
                return
            self._status = status
            conns = [c["conn"] for c in self._clients.values() if c["browser"]]
        for conn in conns:
            try:
                conn.send(status)
            except pipe.PipeError:
                pass  # that browser is going away; its reader thread cleans up

    def _serve(self) -> None:
        while (conn := self._server.accept()) is not None:
            with self._lock:
                cid = self._next_id
                self._next_id += 1
                self._clients[cid] = {"browser": None, "tabs": 0, "conn": conn}
            threading.Thread(target=self._client, args=(cid, conn), name=f"relay-{cid}", daemon=True).start()

    def _client(self, cid: int, conn: pipe.Connection) -> None:
        try:
            while True:
                self._handle(cid, conn, conn.receive())
        except (pipe.PipeError, ValueError):
            pass
        finally:
            conn.close()
            with self._lock:
                was_browser = self._clients.pop(cid)["browser"]
            if was_browser:
                log.info("%s disconnected", was_browser)
                self._notify()

    def _take_screenshots(self) -> None:
        while (item := self._shot_requests.get()) is not None:
            browser, request = item
            try:
                shot = self._shooter.capture(
                    browser, (str(request.get("source")), request.get("tabId")), str(request.get("title") or "")
                )
            except Exception as e:
                log.warning("Screenshot failed: %s", e)
                shot = None
            if shot and self._cases and self._cases.add_screenshot(request, shot.webp, shot.width, shot.height):
                self.screenshots_taken += 1
            else:
                self.screenshots_skipped += 1

    def _handle(self, cid: int, conn: pipe.Connection, message: dict) -> None:
        kind = message.get("type") if isinstance(message, dict) else None
        if kind == "hello":
            browser = str(message.get("browser") or "browser")[:32]
            with self._lock:
                self._clients[cid]["browser"] = browser
            log.info("%s connected", browser)
            conn.send(self._status_message())
            self._notify()
        elif kind == "tabs":
            count = message.get("count")
            if isinstance(count, int) and not isinstance(count, bool):
                with self._lock:
                    self._clients[cid]["tabs"] = max(0, min(MAX_TABS, count))
                self._notify()
        elif kind == "event":
            self.events_received += 1
            if self._cases:
                self._cases.ingest(message)
        elif kind == "screenshot_request":
            with self._lock:
                browser = self._clients[cid]["browser"]
            if not self._is_recording():
                self.screenshots_skipped += 1
                return
            try:
                self._shot_requests.put_nowait((browser, message))
            except queue.Full:
                self.screenshots_skipped += 1  # captures are falling behind; drop, never block
        elif kind == "show":
            self._on_show()
        else:
            log.warning("Ignoring message of type %r", kind)
