"""Companion app entry point: a docked pywebview panel."""

import atexit
import json
import logging
import threading
from importlib import resources

import webview

from . import autostart, diagnostics, hotkeys, pipe, win32
from . import settings as settings_store
from .bridge import Bridge
from .case_store import CaseStore, default_root
from .cases import CaseManager, local_now
from .desktop import DesktopCapture
from .dock import Dock
from .geometry import RAIL_WIDTH, Layout
from .panel import PanelApi
from .refresh import Refresher
from .screenshot import Screenshotter

log = logging.getLogger(__name__)

TITLE = "Inspector's Notebook"
BACKGROUNDS = {"dark": "#0F1215", "light": "#FFFFFF"}


def load_page(theme: str) -> str:
    """The panel as one HTML string.

    Passed to pywebview as `html` rather than a file path, because a path makes
    pywebview serve the files over a local HTTP port and nothing may listen on one (NFR-5).
    """
    ui = resources.files(__package__) / "ui"
    page = (ui / "panel.html").read_text(encoding="utf-8")
    page = page.replace("/* panel.css */", (ui / "panel.css").read_text(encoding="utf-8"), 1)
    page = page.replace("/* panel.js */", (ui / "panel.js").read_text(encoding="utf-8"), 1)
    # Start in the right theme so the page doesn't flash dark before the API answers.
    return page.replace('data-theme="dark"', f'data-theme="{theme}"', 1)


def show_running_instance(name: str) -> bool:
    try:
        conn = pipe.connect(name, timeout_ms=2000)
        conn.send({"type": "show"})
        conn.close()
        return True
    except pipe.PipeError as e:
        log.warning("Inspector is already running but did not answer: %s", e)
        return False


def main() -> int:
    diagnostics.start()  # already started by the packaged app's launcher

    # One companion per user: a second launch just brings the first one forward.
    server = pipe.Server(pipe.default_pipe_name())
    try:
        server.listen()
    except pipe.AlreadyRunning:
        log.info("Already running; showing that one")
        shown = show_running_instance(server.name)
        diagnostics.started()
        return 0 if shown else 1
    log.info("Pipe created")

    win32.enable_per_monitor_dpi()

    path = settings_store.default_path()
    settings = settings_store.load(path)
    settings.start_with_windows = autostart.is_enabled()  # the registry is the source of truth
    dock = Dock()
    cases = CaseManager(
        CaseStore(default_root()), lambda: on_cases_changed(), idle_seconds=win32.idle_seconds, settings=lambda: settings
    )
    api = PanelApi(settings, path, dock, win32.windows_uses_light_theme, cases)
    api._autostart = autostart.set_enabled
    theme = api.get_state()["theme"]

    window = webview.create_window(
        TITLE,
        html=load_page(theme),
        js_api=api,
        width=settings.width,
        height=600,
        x=0,
        y=0,
        min_size=(RAIL_WIDTH, 200),
        frameless=True,
        easy_drag=False,
        on_top=True,
        hidden=True,  # shown once docked, so it never appears in the wrong place
        background_color=BACKGROUNDS[theme],
    )

    loaded = threading.Event()

    def push_state() -> None:
        if loaded.is_set():
            window.evaluate_js(f"render({json.dumps(api.get_state())})")

    def on_listener(listener: dict) -> None:
        api._set_listener(listener)
        push_state()

    def on_show() -> None:
        api._expand()
        if not loaded.is_set():
            return  # still starting; the panel shows itself once docked
        window.show()
        push_state()

    bridge = Bridge(server, on_listener, on_show, Screenshotter(), cases, settings=lambda: settings)

    def refresh() -> None:
        bridge.update_status()
        push_state()

    # A capture burst would otherwise rebuild and resend the whole panel per event (S6).
    refresher = Refresher(refresh)

    def on_cases_changed() -> None:
        refresher.request()

    api._on_settings = on_cases_changed

    # Global shortcuts (docs/decisions.md): each shows the panel when it needs it.
    def call_page(script: str) -> None:
        api._expand()
        window.show()
        push_state()
        if loaded.is_set():
            window.evaluate_js(script)

    def on_record_key() -> None:
        if not cases.summary()["case"]:
            call_page("openStartForm()")
        elif cases.recording:
            cases.pause()
        else:
            cases.resume()

    def on_panel_key() -> None:
        state = api.get_state()
        if state["collapsed"]:
            api._expand()
            window.show()
        else:
            api.toggle_collapse()
        push_state()

    keys = hotkeys.Hotkeys({"note": lambda: call_page("focusNote()"), "record": on_record_key, "panel": on_panel_key})
    # Text from desktop apps the analyst has allowed, while a case records (S9).
    desktop = DesktopCapture(cases.ingest, lambda: cases.recording, lambda: settings, local_now)

    def dock_and_show() -> None:
        window.events.loaded -= dock_and_show
        log.info("Panel loaded; docking")
        hwnd = window.native.Handle.ToInt64()
        dock.start(hwnd, Layout(settings.side, settings.width, settings.dock), theme)
        dock.flush()
        log.info("Docked")
        window.show()
        loaded.set()
        refresher.start()
        desktop.start()
        api._shortcuts_unavailable = [hotkeys.label(name) for name in keys.start()]
        log.info("Started")
        diagnostics.started()

    def shut_down() -> None:
        keys.stop()
        desktop.stop()
        cases.close()
        refresher.stop()
        bridge.stop()
        dock.stop()

    api._window = window
    window.events.loaded += dock_and_show
    window.events.closed += shut_down
    atexit.register(shut_down)
    # Answer the browsers and any second launch at once, not only after WebView2 has loaded:
    # until then the pipe exists but nobody reads it, so the relay shows "connected" to a
    # companion that never replies.
    bridge.start()
    log.info("Serving the pipe; starting WebView2")
    webview.start(gui="edgechromium")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
