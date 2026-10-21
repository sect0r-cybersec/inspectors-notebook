"""The background labelling queue (FR-41 to FR-44).

Rules decide every event on arrival (FR-40); labelling by the model comes after, on one
worker thread, so it never holds up capture or the panel. The newest event is labelled
first so the panel stays current, and older ones when the queue is quiet. Submitting an
event again replaces its pending job, so a job for an event that has since changed is
cancelled (FR-42). Beyond the cap the oldest jobs are dropped: those events stay in the
timeline, marked unlabelled (FR-43).

The model arrives in S7; until then nothing submits jobs.
"""

import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)

CAP = 200  # FR-43


class LabelQueue:
    def __init__(
        self,
        label: Callable[[dict], dict],
        on_labelled: Callable[[int, dict, dict], None],
        on_failed: Callable[[int, dict], None],
        cap: int = CAP,
    ):
        self._label = label
        self._on_labelled = on_labelled
        self._on_failed = on_failed
        self._cap = cap
        self._jobs: dict[int, dict] = {}  # event id to the model's input
        self._running: int | None = None
        self._stale = False  # the running job's event was submitted again
        self._stopped = False
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._work, name="labelling", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._cond:
            self._stopped = True
            self._jobs.clear()
            self._cond.notify_all()
        if self._thread:
            self._thread.join(5)

    @property
    def depth(self) -> int:
        """Events waiting or being labelled, for the footer (FR-44)."""
        with self._cond:
            return len(self._jobs) + (self._running is not None)

    def submit(self, event_id: int, job: dict) -> list[int]:
        """Queue an event, replacing any pending job for it. Returns the events dropped by the cap."""
        with self._cond:
            if self._stopped:
                return []
            self._jobs.pop(event_id, None)
            self._jobs[event_id] = job
            if event_id == self._running:
                self._stale = True
            dropped = []
            while len(self._jobs) > self._cap:
                oldest = min(self._jobs)
                del self._jobs[oldest]
                dropped.append(oldest)
            self._cond.notify()
            return dropped

    def clear(self) -> None:
        """Drop every pending job, as when the case stops; a running job's result is discarded."""
        with self._cond:
            self._jobs.clear()
            self._stale = self._running is not None

    def _work(self) -> None:
        while True:
            with self._cond:
                while not self._jobs and not self._stopped:
                    self._cond.wait()
                if self._stopped:
                    return
                event_id = max(self._jobs)  # newest first (FR-41)
                job = self._jobs.pop(event_id)
                self._running, self._stale = event_id, False
            try:
                labels = self._label(job)
            except Exception:
                log.exception("Labelling event %s failed", event_id)
                labels = None
            with self._cond:
                self._running = None
                stale = self._stale or self._stopped
            if stale:
                continue
            if labels is None:
                self._on_failed(event_id, job)
            else:
                self._on_labelled(event_id, job, labels)
