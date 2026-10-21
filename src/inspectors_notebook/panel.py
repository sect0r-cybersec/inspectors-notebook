"""The API the panel's JavaScript calls through pywebview.

pywebview exposes every public method of this object to the page as
`window.pywebview.api.<name>`, so internal state is kept in underscored attributes.
"""

import re
import threading
from pathlib import Path
from typing import Callable, Protocol

from . import settings as settings_store
from .cases import CaseManager
from .geometry import RAIL_WIDTH, Layout, clamp_width
from .settings import Settings


class DockLike(Protocol):
    def apply(self, layout: Layout) -> None: ...
    def preview(self, layout: Layout) -> None: ...
    def set_theme(self, theme: str) -> None: ...


class PanelApi:
    def __init__(
        self,
        settings: Settings,
        settings_path: Path,
        dock: DockLike,
        windows_uses_light_theme: Callable[[], bool],
        cases: CaseManager | None = None,
    ):
        self._settings = settings
        self._path = settings_path
        self._dock = dock
        self._windows_light = windows_uses_light_theme
        self._cases = cases
        self._collapsed = False
        self._listener = {"browsers": 0, "tabs": 0}
        self._lock = threading.Lock()

    # Called from Python

    def _effective_theme(self) -> str:
        if self._settings.theme == "system":
            return "light" if self._windows_light() else "dark"
        return self._settings.theme

    def _layout(self, width: int | None = None) -> Layout:
        if self._collapsed:
            width = RAIL_WIDTH
        elif width is None:
            width = self._settings.width
        return Layout(self._settings.side, width, self._settings.dock)

    def _save(self) -> None:
        settings_store.save(self._settings, self._path)

    def _set_listener(self, listener: dict) -> None:
        with self._lock:
            self._listener = dict(listener)

    def _expand(self) -> None:
        with self._lock:
            if self._collapsed:
                self._collapsed = False
                self._dock.apply(self._layout())

    # Called from the page

    def get_state(self) -> dict:
        with self._lock:
            state = {
                "side": self._settings.side,
                "theme": self._effective_theme(),
                "width": self._settings.width,
                "collapsed": self._collapsed,
                "listener": dict(self._listener),
            }
        state.update(self._cases.summary() if self._cases else {"case": None, "suggestion": None})
        return state

    # Cases (FR-1, FR-3, FR-8, FR-21)

    def start_case(self, form: dict) -> dict:
        """Start a case by hand. Entities are one per line or comma separated."""
        entities = [e for e in re.split(r"[,\n]", str(form.get("entities") or "")) if e.strip()]
        self._cases.start(
            incident_id=str(form.get("incidentId") or ""),
            title=str(form.get("title") or ""),
            entities=entities,
            console=form.get("console") or None,
        )
        return self.get_state()

    def pause_case(self) -> dict:
        self._cases.pause()
        return self.get_state()

    def resume_case(self) -> dict:
        self._cases.resume()
        return self.get_state()

    def stop_case(self) -> dict:
        self._cases.stop()
        return self.get_state()

    def add_entity(self, value: str) -> dict:
        self._cases.add_entity(str(value))
        return self.get_state()

    def remove_entity(self, value: str) -> dict:
        self._cases.remove_entity(str(value))
        return self.get_state()

    def accept_suggestion(self) -> dict:
        self._cases.accept_suggestion()
        return self.get_state()

    def dismiss_suggestion(self) -> dict:
        self._cases.dismiss_suggestion()
        return self.get_state()

    def toggle_side(self) -> dict:
        with self._lock:
            self._settings.side = "left" if self._settings.side == "right" else "right"
            self._save()
            self._dock.apply(self._layout())
        return self.get_state()

    def toggle_collapse(self) -> dict:
        with self._lock:
            self._collapsed = not self._collapsed
            self._dock.apply(self._layout())
        return self.get_state()

    def toggle_theme(self) -> dict:
        """Switch between dark and light. From "system", switch away from what Windows shows."""
        with self._lock:
            self._settings.theme = "light" if self._effective_theme() == "dark" else "dark"
            self._save()
            self._dock.set_theme(self._settings.theme)
        return self.get_state()

    def preview_width(self, width: int) -> None:
        """Resize the panel while the inner edge is being dragged, without saving."""
        with self._lock:
            if not self._collapsed:
                self._dock.preview(self._layout(clamp_width(width)))

    def set_width(self, width: int) -> dict:
        with self._lock:
            self._settings.width = clamp_width(width)
            self._save()
            self._dock.apply(self._layout())
        return self.get_state()
