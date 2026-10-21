import time

from inspectors_notebook.refresh import Refresher


def test_a_burst_of_requests_is_coalesced_and_the_last_state_is_shown():
    value = {"n": 0}
    seen = []
    r = Refresher(lambda: seen.append(value["n"]), interval=0.05)
    r.start()
    try:
        r.request()
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            value["n"] += 1
            r.request()
            time.sleep(0.0005)
        last = value["n"]
        time.sleep(0.2)
    finally:
        r.stop()
    assert seen[-1] == last  # the panel ends up current
    assert 5 <= len(seen) <= 15  # about one refresh per interval, not one per request
    assert last > 100


def test_a_failing_refresh_does_not_stop_later_ones():
    calls = []

    def refresh():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("window closed")

    r = Refresher(refresh, interval=0.01)
    r.start()
    try:
        r.request()
        time.sleep(0.05)
        r.request()
        time.sleep(0.05)
    finally:
        r.stop()
    assert len(calls) == 2
