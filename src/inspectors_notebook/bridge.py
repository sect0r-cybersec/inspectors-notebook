"""The companion's end of the pipe: one relay connection per browser (FR-36).

Tracks which browsers are connected and how many console tabs they report, and
answers each hello with the recording state. Capture events are counted but not
kept: the case manager that stores them arrives in S4.
"""

import logging
import threading
from typing import Callable

from . import pipe

log = logging.getLogger(__name__)

MAX_TABS = 10_000


class Bridge:
    def __init__(
        self,
        server: pipe.Server,
        on_listener: Callable[[dict], None],
        on_show: Callable[[], None],
    ):
        self._server = server
        self._on_listener = on_listener
        self._on_show = on_show
        self._lock = threading.Lock()
        self._clients: dict[int, dict] = {}
        self._next_id = 0
        self.events_received = 0

    def start(self) -> None:
        threading.Thread(target=self._serve, name="bridge", daemon=True).start()

    def stop(self) -> None:
        self._server.close()

    def listener(self) -> dict:
        with self._lock:
            browsers = [c for c in self._clients.values() if c["browser"]]
            return {"browsers": len(browsers), "tabs": sum(c["tabs"] for c in browsers)}

    def _notify(self) -> None:
        self._on_listener(self.listener())

    def _serve(self) -> None:
        while (conn := self._server.accept()) is not None:
            with self._lock:
                cid = self._next_id
                self._next_id += 1
                self._clients[cid] = {"browser": None, "tabs": 0}
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

    def _handle(self, cid: int, conn: pipe.Connection, message: dict) -> None:
        kind = message.get("type") if isinstance(message, dict) else None
        if kind == "hello":
            browser = str(message.get("browser") or "browser")[:32]
            with self._lock:
                self._clients[cid]["browser"] = browser
            log.info("%s connected", browser)
            conn.send({"type": "status", "recording": False})
            self._notify()
        elif kind == "tabs":
            count = message.get("count")
            if isinstance(count, int) and not isinstance(count, bool):
                with self._lock:
                    self._clients[cid]["tabs"] = max(0, min(MAX_TABS, count))
                self._notify()
        elif kind == "event":
            self.events_received += 1
        elif kind == "show":
            self._on_show()
        else:
            log.warning("Ignoring message of type %r", kind)
