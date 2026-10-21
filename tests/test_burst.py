"""S6 exit: a burst of 500 events keeps its order and never freezes the panel, and capped
labelling jobs stay in the timeline unlabelled."""

import sys
import threading
import time
import uuid

import pytest

from inspectors_notebook.case_store import CaseStore
from inspectors_notebook.cases import CaseManager
from inspectors_notebook.labelling import CAP
from inspectors_notebook.panel import PanelApi
from inspectors_notebook.refresh import Refresher
from inspectors_notebook.settings import Settings

BURST = 500


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def burst_event(n):
    """A query from the console; seq and ts are stamped by the extension (FR-39)."""
    second = f"{n % 60:02d}.{n % 1000:03d}"
    return {
        "type": "event", "kind": "query", "source": "chrome-1", "seq": n, "tabId": 1, "console": "defender",
        "ts": f"2026-10-21T14:{n // 60:02d}:{second}+01:00", "queryId": f"q{n}", "query": f"DeviceInfo | where DeviceName == 'HOST-{n}'",
    }  # fmt: skip


class SlowModel:
    """Stands in for the S7 model: every job waits until the test lets it go."""

    def __init__(self):
        self.gate = threading.Event()
        self.calls = []

    def __call__(self, job):
        self.calls.append(job["event"]["seq"])
        self.gate.wait(10)
        return {"type": "hunting query"}


@pytest.fixture
def case(tmp_path):
    model = SlowModel()
    settings = Settings()
    cases = CaseManager(CaseStore(tmp_path / "cases"), settings=lambda: settings, labeller=model)
    api = PanelApi(settings, tmp_path / "settings.json", None, lambda: False, cases)
    cases.start(title="Burst", entities=["HOST-1"])
    yield cases, api, model
    model.gate.set()
    cases.close()


def test_a_burst_keeps_its_order_and_capped_jobs_stay_unlabelled(case):
    cases, api, model = case
    started = time.monotonic()
    for n in range(1, BURST + 1):
        cases.ingest(burst_event(n))
    elapsed = time.monotonic() - started

    # Capture never waits for labelling: the whole burst went in while the model was stuck.
    assert len(model.calls) <= 1 and elapsed < 10
    assert [e["seq"] for e, _ in cases.events()] == list(range(1, BURST + 1))

    state = api.get_state()
    assert len(state["timeline"]) == BURST  # nothing dropped from the timeline (FR-43)
    assert [int(i["code"].rsplit("-", 1)[1].rstrip("'")) for i in state["timeline"]] == list(range(BURST, 0, -1))
    assert state["case"]["labelling"] == CAP + 1  # the cap, plus the job the model is on
    unlabelled = [i["ids"][0] for i in reversed(state["timeline"]) if i["unlabelled"]]
    assert unlabelled == list(range(2, BURST - CAP + 1))  # the oldest, beyond the cap

    model.gate.set()
    assert wait_for(lambda: cases.summary()["case"]["labelling"] == 0)
    assert model.calls[1:] == list(range(BURST, BURST - CAP, -1))  # newest first (FR-41)
    labelled = {i for i, m in cases.marks().items() if "labels" in m}
    assert labelled == {1, *range(BURST - CAP + 1, BURST + 1)}


def test_the_panel_refreshes_a_few_times_per_second_during_a_burst(case):
    """The panel used to be rebuilt and resent per event: about 20 s of work for 1,000."""
    cases, api, model = case
    model.gate.set()
    refreshes = []
    refresher = Refresher(lambda: refreshes.append(len(api.get_state()["timeline"])))
    cases._on_change = refresher.request
    refresher.start()
    try:
        started = time.monotonic()
        for n in range(1, BURST + 1):
            cases.ingest(burst_event(n))
        elapsed = time.monotonic() - started
        assert wait_for(lambda: refreshes and refreshes[-1] == BURST)
    finally:
        refresher.stop()
    assert len(refreshes) <= elapsed / 0.2 + 5  # one per interval, however many events
    assert elapsed < 10


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_a_burst_over_the_pipe_arrives_in_order(tmp_path):
    from inspectors_notebook import pipe
    from inspectors_notebook.bridge import Bridge
    from inspectors_notebook.screenshot import Shot

    class NoShots:
        def capture(self, browser, tab_key, title):
            return Shot(b"", 0, 0)

    name = rf"\\.\pipe\InspectorsNotebook.test.{uuid.uuid4()}"
    server = pipe.Server(name)
    server.listen()
    cases = CaseManager(CaseStore(tmp_path / "cases"))
    bridge = Bridge(server, lambda listener: None, lambda: None, NoShots(), cases)
    bridge.start()
    client = pipe.connect(name, timeout_ms=2000)
    try:
        cases.start(title="Burst")
        client.send({"type": "hello", "browser": "chrome"})
        client.receive()
        for n in range(1, BURST + 1):
            client.send(burst_event(n))
        assert wait_for(lambda: len(cases.events()) == BURST)
        assert [e["seq"] for e, _ in cases.events()] == list(range(1, BURST + 1))
    finally:
        client.close()
        bridge.stop()
