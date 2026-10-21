"""Companion app entry point: a docked pywebview panel."""

import atexit
import json
import logging
import threading
from importlib import resources

import webview

from . import pipe, win32
from . import settings as settings_store
from .bridge import Bridge
from .dock import Dock
from .geometry import RAIL_WIDTH, Layout
from .panel import PanelApi

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


def show_running_instance(name: str) -> None:
    try:
        conn = pipe.connect(name, timeout_ms=2000)
        conn.send({"type": "show"})
        conn.close()
    except pipe.PipeError as e:
        log.warning("Inspector is already running but did not answer: %s", e)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # One companion per user: a second launch just brings the first one forward.
    server = pipe.Server(pipe.default_pipe_name())
    try:
        server.listen()
    except pipe.AlreadyRunning:
        show_running_instance(server.name)
        return

    win32.enable_per_monitor_dpi()

    path = settings_store.default_path()
    settings = settings_store.load(path)
    dock = Dock()
    api = PanelApi(settings, path, dock, win32.windows_uses_light_theme)
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
        window.show()
        push_state()

    bridge = Bridge(server, on_listener, on_show)

    def dock_and_show() -> None:
        window.events.loaded -= dock_and_show
        hwnd = window.native.Handle.ToInt64()
        dock.start(hwnd, Layout(settings.side, settings.width, settings.dock), theme)
        dock.flush()
        window.show()
        loaded.set()
        bridge.start()

    def shut_down() -> None:
        bridge.stop()
        dock.stop()

    window.events.loaded += dock_and_show
    window.events.closed += shut_down
    atexit.register(shut_down)
    webview.start(gui="edgechromium")


if __name__ == "__main__":
    main()
