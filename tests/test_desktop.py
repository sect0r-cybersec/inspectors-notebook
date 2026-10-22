import ctypes
import os
import subprocess
import sys
import time
import uuid

import pytest

if sys.platform != "win32":
    pytest.skip("Windows only", allow_module_level=True)

from inspectors_notebook import desktop, export, settings as settings_store, timeline
from inspectors_notebook.case_store import CaseStore
from inspectors_notebook.cases import CaseManager
from inspectors_notebook.desktop import MAX_TEXT, DesktopCapture, Window, new_lines, screen_lines
from inspectors_notebook.rules import HIDE, KEEP
from inspectors_notebook.settings import Settings

TERMINAL = Window(hwnd=101, pid=4242, app="WindowsTerminal.exe", title="jdoe@lab: ~")
RDP = Window(hwnd=202, pid=4343, app="mstsc.exe", title="lab-dc01 - Remote Desktop Connection")


# What is new on screen


def test_only_lines_new_on_screen_are_sent():
    assert new_lines([], ["$ whoami", "lab\\jdoe"]) == ["$ whoami", "lab\\jdoe"]  # first look: all of it
    scrolled = ["lab\\jdoe", "$ hostname", "HOST-12"]
    assert new_lines(["$ whoami", "lab\\jdoe"], scrolled) == ["$ hostname", "HOST-12"]  # output scrolls in below
    assert new_lines(scrolled, scrolled) == []


def test_ocr_jitter_on_a_line_already_seen_is_not_new():
    seen = ["Inspector S9 probe: user jdoe on HOST-12 from"]
    assert new_lines(seen, ["Inspector S9 probe: user jdoe on HOST\ufffd12 from", "Event 4624 logon"]) == ["Event 4624 logon"]


def test_screen_text_is_split_into_trimmed_lines():
    assert screen_lines("a   \r\n\r\n  b\rc\n   ") == ["a", "  b", "c"]


# The capture loop


class FakeReader:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = 0

    def read(self, hwnd):
        self.calls += 1
        return self.texts.pop(0) if self.texts else None


def make(windows, uia=None, ocr=None, recording=True, **settings):
    s = Settings(desktop_capture=True, desktop_apps=["windowsterminal.exe", "mstsc.exe"])
    for name, value in settings.items():
        setattr(s, name, value)
    events = []
    state = {"recording": recording}
    windows = iter(windows)
    capture = DesktopCapture(
        events.append, lambda: state["recording"], lambda: s, lambda: "2026-10-22T10:00:00.000+01:00",
        foreground=lambda: next(windows),
        uia=(lambda: uia) if uia is not None else _unavailable,
        ocr=(lambda: ocr) if ocr is not None else _unavailable,
    )
    return capture, events, state


def _unavailable():
    raise RuntimeError("not on this machine")


def test_nothing_is_read_unless_switched_on_and_recording():
    uia = FakeReader(["text"])
    capture, events, _ = make([TERMINAL], uia=uia, desktop_capture=False)
    capture.poll()
    capture, events2, _ = make([TERMINAL], uia=uia, recording=False)
    capture.poll()
    assert events == events2 == [] and uia.calls == 0
    assert Settings().desktop_capture is False and Settings().desktop_apps == []  # off by default


def test_only_allowed_apps_are_read_and_never_inspectors_own_window():
    uia = FakeReader(["text"] * 3)
    other = Window(303, 4444, "notepad.exe", "secrets.txt")
    own = Window(404, os.getpid(), "WindowsTerminal.exe", "Inspector's Notebook")
    capture, events, _ = make([other, own], uia=uia)
    capture.poll()
    capture.poll()
    assert events == [] and uia.calls == 0


def test_a_terminal_sends_its_window_then_only_new_lines():
    uia = FakeReader(["$ whoami\nlab\\jdoe", "$ whoami\nlab\\jdoe", "lab\\jdoe\n$ hostname\nHOST-12"])
    capture, events, _ = make([TERMINAL] * 3, uia=uia)
    for _ in range(3):
        capture.poll()
    assert [e["kind"] for e in events] == ["desktop_window", "desktop_text", "desktop_text"]
    assert events[0] == {"type": "event", "kind": "desktop_window", "source": "desktop", "seq": 1,
                         "ts": "2026-10-22T10:00:00.000+01:00", "app": "WindowsTerminal.exe", "title": "jdoe@lab: ~"}  # fmt: skip
    assert (events[1]["method"], events[1]["text"]) == ("uia", "$ whoami\nlab\\jdoe")
    assert events[2]["text"] == "$ hostname\nHOST-12"


def test_windows_with_no_text_to_automation_fall_back_to_ocr():
    ocr = FakeReader(["Event Viewer\n4624 An account was successfully logged on"])
    capture, events, _ = make([RDP], uia=FakeReader([None]), ocr=ocr)
    capture.poll()
    assert [(e["kind"], e.get("method")) for e in events] == [("desktop_window", None), ("desktop_text", "ocr")]


def test_an_unavailable_reader_is_skipped_and_not_retried():
    ocr = FakeReader(["remote text", "remote text"])
    capture, events, _ = make([RDP, RDP], ocr=ocr)  # no UI Automation at all
    capture.poll()
    capture.poll()
    assert capture._readers["uia"] is None and ocr.calls == 2
    assert [e["kind"] for e in events] == ["desktop_window", "desktop_text"]


def test_switching_windows_is_an_event_but_a_running_commands_title_is_not():
    uia = FakeReader([None] * 5)
    running = Window(TERMINAL.hwnd, TERMINAL.pid, TERMINAL.app, "jdoe@lab: ~ - ping -n 5 10.0.4.17")
    capture, events, state = make([TERMINAL, running, RDP, TERMINAL, TERMINAL], uia=uia)
    capture.poll()
    capture.poll()  # same window, new title: no event
    capture.poll()
    capture.poll()
    state["recording"] = False
    capture.poll()
    state["recording"] = True
    capture.poll()  # coming back after a pause is a switch again
    assert [(e["app"], e["title"]) for e in events] == [
        ("WindowsTerminal.exe", "jdoe@lab: ~"), ("mstsc.exe", "lab-dc01 - Remote Desktop Connection"),
        ("WindowsTerminal.exe", "jdoe@lab: ~"), ("WindowsTerminal.exe", "jdoe@lab: ~"),
    ]  # fmt: skip


def test_long_text_is_capped():
    capture, events, _ = make([TERMINAL], uia=FakeReader(["\n".join(f"line {i:05d} " + "x" * 80 for i in range(200))]))
    capture.poll()
    assert len(events[-1]["text"]) == MAX_TEXT


# The same rules, timeline and export as browser events (FR-47)


def test_desktop_events_follow_the_rules_and_reach_the_export(tmp_path):
    cases = CaseManager(CaseStore(tmp_path / "cases"), now=lambda: "2026-10-22T10:00:00.000+01:00")
    cases.start(title="Lateral movement", entities=["HOST-12"])
    capture, _, _ = make([RDP, RDP], ocr=FakeReader(["Server Manager", "Server Manager\nLogon from HOST-12"]))
    capture._ingest = cases.ingest
    capture.poll()
    capture.poll()
    decisions = [(e["kind"], d.disposition, d.reason) for e, d in cases.events()]
    assert decisions == [("desktop_window", KEEP, "console"), ("desktop_text", KEEP, "console"), ("desktop_text", KEEP, "entity")]

    items = timeline.build([e for e, _ in cases.events()], [d for _, d in cases.events()], {})
    assert [(i.kind, i.label) for i in items] == [("window", "mstsc.exe"), ("desktop", "mstsc.exe (OCR, approximate)"), ("desktop", "mstsc.exe (OCR, approximate)")]
    text = export.render(cases.case_meta(), items, export.Options(fmt="text"))
    assert "WINDOW   mstsc.exe: lab-dc01 - Remote Desktop Connection" in text
    assert "DESKTOP  Text in mstsc.exe (OCR, approximate)" in text and "Logon from HOST-12" in text


def test_idle_desktop_text_is_hidden_like_any_other_event(tmp_path):
    cases = CaseManager(CaseStore(tmp_path / "cases"), idle_seconds=lambda: 10_000)
    cases.start(title="x")
    cases.ingest({"type": "event", "kind": "desktop_text", "source": "desktop", "app": "mstsc.exe", "text": "screen saver"})
    assert cases.events()[0][1].disposition == HIDE


def test_allowed_apps_are_program_names_kept_once():
    s = settings_store.changed(Settings(), {"desktop_apps": ["mstsc.exe", "WindowsTerminal.exe", "MSTSC.EXE"]})
    assert s.desktop_apps == ["MSTSC.EXE", "WindowsTerminal.exe"]
    for bad in (["C:\\Windows\\notepad.exe"], ["notepad"], ["x.exe"] * 21, "mstsc.exe", [42]):
        assert settings_store.changed(Settings(), {"desktop_apps": bad}).desktop_apps == []


# The real readers


@pytest.mark.desktop
def test_ui_automation_reads_a_console_window_exactly():
    marker = f"inspector-{uuid.uuid4().hex[:8]}"
    proc = subprocess.Popen(
        ["cmd.exe", "/k", f"title {marker} & echo user jdoe on HOST-12 from 10.0.4.17 {marker}"],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    try:
        hwnd = None
        deadline = time.monotonic() + 15
        while not hwnd and time.monotonic() < deadline:
            time.sleep(0.3)
            hwnd = _window_titled(marker)
        assert hwnd, "the console window did not appear"
        text = None
        while time.monotonic() < deadline and (not text or "10.0.4.17" not in text):
            text = desktop.UiaReader().read(hwnd)
            time.sleep(0.3)
        assert f"user jdoe on HOST-12 from 10.0.4.17 {marker}" in screen_lines(text or "")
    finally:
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, 0x10, 0, 0)  # WM_CLOSE
        proc.kill()


def _window_titled(marker: str) -> int | None:
    found = []

    def visit(hwnd, _):
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, title, length + 1)
        if marker in title.value and ctypes.windll.user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    ctypes.windll.user32.EnumWindows(desktop.WNDENUMPROC(visit), 0)
    return found[0] if found else None


@pytest.mark.desktop
def test_windows_ocr_reads_clear_text():
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (900, 120), "white")
    font = ImageFont.truetype(os.path.join(os.environ["WINDIR"], "Fonts", "arial.ttf"), 40)
    ImageDraw.Draw(image).text((20, 30), "Logon from HOST-12 by jdoe", fill="black", font=font)
    try:
        reader = desktop.OcrReader()
    except RuntimeError as e:
        pytest.skip(f"Windows OCR is not available on this machine: {e}")
    assert reader.recognise(image) == "Logon from HOST-12 by jdoe"
