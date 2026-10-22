"""The API the panel's JavaScript calls through pywebview.

pywebview exposes every public method of this object to the page as
`window.pywebview.api.<name>`, so internal state is kept in underscored attributes.
"""

import re
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Protocol

from . import desktop, export, timeline
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
        self._window = None  # set by the app, for file dialogs
        self._on_settings: Callable[[], None] = lambda: None
        self._shortcuts_unavailable: list[str] = []
        self._autostart: Callable[[bool], None] = lambda enabled: None

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
        state["timeline"] = []
        if state["case"]:
            items = self._items()
            entities = state["case"]["entities"]
            state["timeline"] = [timeline.view(i, entities, utc=self._settings.show_utc) for i in reversed(items)]
            state["case"]["counts"] = timeline.counts(items)
        return state

    def _items(self) -> list[timeline.Item]:
        pairs = self._cases.events()
        return timeline.build([e for e, _ in pairs], [d for _, d in pairs], self._cases.marks())

    # Timeline (FR-23 to FR-26)

    def add_note(self, text: str) -> dict:
        self._cases.add_note(str(text))
        return self.get_state()

    def star_item(self, ids: list, starred: bool) -> dict:
        self._cases.set_star(int(ids[0]), bool(starred))
        return self.get_state()

    def comment_item(self, ids: list, text: str) -> dict:
        self._cases.set_annotation(int(ids[0]), str(text))
        return self.get_state()

    def pin_item(self, ids: list, pinned: bool) -> dict:
        self._cases.set_pin(int(ids[0]), bool(pinned))
        return self.get_state()

    def decide_item(self, ids: list, disposition: str | None) -> dict:
        """Keep or hide every event in an item (a query and its results); None restores."""
        for event_id in ids:
            self._cases.set_decision(int(event_id), disposition or None)
        return self.get_state()

    # Export (FR-27, FR-28)

    def _export_options(self, form: dict) -> export.Options:
        defaults = (("findings", True), ("timeline", True), ("rows", True), ("notes", True), ("hidden", False), ("screenshots", True))
        flags = {k: bool(form.get(k, default)) for k, default in defaults}
        fmt = form.get("fmt") if form.get("fmt") in ("text", "markdown", "html") else "text"
        return export.Options(fmt=fmt, row_limit=self._settings.export_rows, utc=self._settings.show_utc, **flags)

    def _render(self, form: dict) -> tuple[str, export.Options]:
        opts = self._export_options(form)
        return export.render(self._cases.case_meta(), self._items(), opts), opts

    def export_preview(self, form: dict) -> dict:
        text, opts = self._render(form)
        items = self._items()
        return {
            "text": text,
            "kept": sum(1 for i in items if i.disposition == "keep"),
            "findings": sum(1 for i in items if i.star),
            "screenshots": sum(1 for i in items if i.kind == "screenshot" and i.pinned),
            "rowLimit": opts.row_limit,
        }

    def export_copy(self, form: dict) -> bool:
        from . import win32

        text, opts = self._render(form)
        win32.set_clipboard(text, html=text if opts.fmt == "html" else None)
        self._cases.mark_exported()
        return True

    def _save_path(self, name: str, kind: str) -> Path | None:
        import webview

        chosen = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name, file_types=(kind,))
        if not chosen:
            return None
        return Path(chosen[0] if isinstance(chosen, (list, tuple)) else chosen)

    def _file_stem(self) -> str:
        meta = self._cases.case_meta()
        return f"case-{meta.get('incidentId') or meta['id']}"

    def export_save(self, form: dict) -> str | None:
        text, opts = self._render(form)
        suffix, kind = {
            "text": (".txt", "Text (*.txt)"),
            "markdown": (".md", "Markdown (*.md)"),
            "html": (".html", "HTML (*.html)"),
        }[opts.fmt]
        path = self._save_path(self._file_stem() + suffix, kind)
        if not path:
            return None
        path.write_text(text, encoding="utf-8")
        self._cases.mark_exported()
        return str(path)

    def export_screenshots(self) -> str | None:
        files = export.screenshot_files(self._cases.case_dir(), self._items())
        if not files:
            return None
        path = self._save_path(self._file_stem() + "-screenshots.zip", "Zip archive (*.zip)")
        if not path:
            return None
        export.write_zip(path, files)
        return str(path)

    # Cases screen (FR-29 to FR-32)

    def cases_state(self) -> dict:
        return self._cases.cache_state()

    def open_case(self, case_id: str) -> dict:
        self._cases.open_case(str(case_id))
        return self.get_state()

    def pin_case(self, case_id: str, pinned: bool) -> dict:
        self._cases.pin_case(str(case_id), bool(pinned))
        return self._cases.cache_state()

    def delete_case(self, case_id: str) -> dict:
        self._cases.delete_case(str(case_id))
        return self._cases.cache_state()

    def keep_case(self, case_id: str) -> dict:
        self._cases.keep_case(str(case_id))
        return self._cases.cache_state()

    # Settings screen

    def desktop_open_apps(self) -> list[dict]:
        """Programs with a window open, for the desktop capture allow list (FR-45)."""
        return desktop.open_apps()

    def get_settings(self) -> dict:
        with self._lock:
            return {**asdict(self._settings), "shortcutsUnavailable": list(self._shortcuts_unavailable)}

    def update_settings(self, changes: dict) -> dict:
        with self._lock:
            before = asdict(self._settings)
            after = asdict(settings_store.changed(self._settings, dict(changes)))
            for name, value in after.items():
                setattr(self._settings, name, value)  # in place: the case manager and bridge read this object
            self._save()
            if any(before[k] != after[k] for k in ("side", "dock", "width")):
                self._dock.apply(self._layout())
            if before["theme"] != after["theme"]:
                self._dock.set_theme(self._effective_theme())
            if before["start_with_windows"] != after["start_with_windows"]:
                self._autostart(after["start_with_windows"])
        self._on_settings()
        return self.get_settings()

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
