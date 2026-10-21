import threading
import time

import pytest

from inspectors_notebook.labelling import LabelQueue


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class Labeller:
    """Labels instantly, except that the first job waits at the gate until released."""

    def __init__(self, fail=()):
        self.calls = []
        self.gate = threading.Event()
        self.waiting = threading.Event()
        self.fail = fail

    def __call__(self, job):
        self.calls.append(job["v"])
        if len(self.calls) == 1:
            self.waiting.set()
            self.gate.wait(5)
        if job["v"] in self.fail:
            raise RuntimeError("model error")
        return {"label": job["v"]}


@pytest.fixture
def run():
    queues = []

    def make(labeller, cap=200):
        done, failed = [], []
        q = LabelQueue(labeller, lambda i, job, labels: done.append((i, labels["label"])), lambda i, job: failed.append(i), cap)
        q.done, q.failed = done, failed
        q.start()
        queues.append(q)
        return q

    yield make
    for q in queues:
        q.stop()


def test_newest_events_are_labelled_first(run):  # FR-41
    labeller = Labeller()
    q = run(labeller)
    q.submit(1, {"v": "e1"})
    assert labeller.waiting.wait(2)
    for i in range(2, 6):
        q.submit(i, {"v": f"e{i}"})
    assert q.depth == 5
    labeller.gate.set()
    assert wait_for(lambda: len(q.done) == 5)
    assert labeller.calls == ["e1", "e5", "e4", "e3", "e2"]
    assert q.depth == 0


def test_beyond_the_cap_the_oldest_jobs_are_dropped(run):  # FR-43
    labeller = Labeller()
    q = run(labeller, cap=3)
    q.submit(1, {"v": 1})
    assert labeller.waiting.wait(2)
    dropped = [d for i in range(2, 8) for d in q.submit(i, {"v": i})]
    assert dropped == [2, 3, 4]
    assert q.depth == 4  # three waiting and one running
    labeller.gate.set()
    assert wait_for(lambda: len(q.done) == 4)
    assert [i for i, _ in q.done] == [1, 7, 6, 5]


def test_a_changed_event_replaces_its_pending_job(run):  # FR-42
    labeller = Labeller()
    q = run(labeller)
    q.submit(1, {"v": "first"})
    assert labeller.waiting.wait(2)
    q.submit(2, {"v": "old title"})
    q.submit(2, {"v": "new title"})
    labeller.gate.set()
    assert wait_for(lambda: len(q.done) == 2)
    assert q.done == [(1, "first"), (2, "new title")]


def test_a_result_for_an_event_that_changed_while_labelling_is_discarded(run):  # FR-42
    labeller = Labeller()
    q = run(labeller)
    q.submit(1, {"v": "before"})
    assert labeller.waiting.wait(2)
    q.submit(1, {"v": "after"})
    labeller.gate.set()
    assert wait_for(lambda: len(q.done) == 1)
    time.sleep(0.1)
    assert q.done == [(1, "after")]


def test_clearing_drops_pending_jobs_and_the_running_result(run):
    labeller = Labeller()
    q = run(labeller)
    q.submit(1, {"v": 1})
    assert labeller.waiting.wait(2)
    q.submit(2, {"v": 2})
    q.clear()
    labeller.gate.set()
    assert wait_for(lambda: q.depth == 0)
    time.sleep(0.1)
    assert q.done == [] and labeller.calls == [1]


def test_a_failed_job_is_reported_and_the_queue_carries_on(run):
    labeller = Labeller(fail={2})
    labeller.gate.set()
    q = run(labeller)
    for i in (1, 2, 3):
        q.submit(i, {"v": i})
        assert wait_for(lambda: q.depth == 0)
    assert q.failed == [2]
    assert [i for i, _ in q.done] == [1, 3]
