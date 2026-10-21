"""Coalesced panel refreshes, so a burst of captures never freezes the panel (S6).

Every capture changes the case, but rebuilding and sending the whole panel state per
event made a burst of 1,000 events cost about 20 s. Requests set a flag; one thread
refreshes at once, then at most once per interval while requests keep coming, and always
once more after the last request so the panel ends up current.
"""

import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)

INTERVAL = 0.2  # seconds between refreshes during a burst


class Refresher:
    def __init__(self, refresh: Callable[[], None], interval: float = INTERVAL):
        self._refresh = refresh
        self._interval = interval
        self._wanted = threading.Event()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="refresh", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        self._wanted.set()
        if self._thread:
            self._thread.join(5)

    def request(self) -> None:
        self._wanted.set()

    def _run(self) -> None:
        while True:
            self._wanted.wait()
            if self._stopped.is_set():
                return
            self._wanted.clear()
            try:
                self._refresh()
            except Exception:
                log.exception("Refreshing the panel failed")
            if self._stopped.wait(self._interval):
                return
