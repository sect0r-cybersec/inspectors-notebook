"""Cases on disk, one folder each, as plain files (see docs/decisions.md).

    <root>/<case id>/case.json        metadata, rewritten atomically on change
    <root>/<case id>/events.jsonl     every captured event, appended
    <root>/<case id>/actions.jsonl    the analyst's keep, hide, star, annotation and pin
                                      actions on events, appended
    <root>/<case id>/screenshots/     WebP files named after their event

Appending means a crash loses at most the line being written; nothing earlier.
"""

import json
import os
import re
import shutil
from pathlib import Path

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


def default_root() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "InspectorsNotebook" / "cases"


class CaseStore:
    def __init__(self, root: Path):
        self.root = root

    def _dir(self, case_id: str) -> Path:
        if not _SAFE_ID.match(case_id):
            raise ValueError(f"Not a case id: {case_id!r}")
        return self.root / case_id

    def create(self, meta: dict) -> None:
        folder = self._dir(meta["id"])
        (folder / "screenshots").mkdir(parents=True, exist_ok=False)
        self.save_meta(meta)

    def save_meta(self, meta: dict) -> None:
        folder = self._dir(meta["id"])
        tmp = folder / "case.json.tmp"
        tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, folder / "case.json")

    def _append(self, case_id: str, name: str, record: dict) -> None:
        with open(self._dir(case_id) / name, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def append_event(self, case_id: str, event: dict) -> None:
        self._append(case_id, "events.jsonl", event)

    def append_action(self, case_id: str, event_id: int, field: str, value) -> None:
        """Record one change to an event: disposition, star, annotation or pin. None clears it."""
        self._append(case_id, "actions.jsonl", {"event": event_id, "field": field, "value": value})

    def save_screenshot(self, case_id: str, event_id: int, data: bytes) -> str:
        name = f"screenshots/{event_id:06d}.webp"
        (self._dir(case_id) / name).write_bytes(data)
        return name

    @staticmethod
    def _read_lines(path: Path) -> list[dict]:
        if not path.exists():
            return []
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except ValueError:
                pass  # a line cut short by a crash
        return records

    def load(self, case_id: str) -> tuple[dict, list[dict], dict[int, dict]]:
        """Metadata, events, and each event's current marks after replaying the actions."""
        folder = self._dir(case_id)
        meta = json.loads((folder / "case.json").read_text(encoding="utf-8"))
        events = self._read_lines(folder / "events.jsonl")
        marks: dict[int, dict] = {}
        for action in self._read_lines(folder / "actions.jsonl"):
            event_marks = marks.setdefault(action["event"], {})
            if action.get("value") in (None, False, ""):
                event_marks.pop(action["field"], None)  # later actions replace earlier ones
            else:
                event_marks[action["field"]] = action["value"]
        return meta, events, {k: v for k, v in marks.items() if v}

    def list(self) -> list[dict]:
        if not self.root.exists():
            return []
        metas = []
        for folder in self.root.iterdir():
            try:
                metas.append(json.loads((folder / "case.json").read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(metas, key=lambda m: m.get("lastActivity", ""), reverse=True)

    def find_by_incident(self, console: str | None, incident_id: str) -> str | None:
        for meta in self.list():
            if meta.get("incidentId") == incident_id and meta.get("console") == console:
                return meta["id"]
        return None

    def size(self, case_id: str) -> int:
        """Bytes on disk for one case."""
        return sum(f.stat().st_size for f in self._dir(case_id).rglob("*") if f.is_file())

    def update_meta(self, case_id: str, **changes) -> dict:
        meta = json.loads((self._dir(case_id) / "case.json").read_text(encoding="utf-8"))
        meta.update(changes)
        self.save_meta(meta)
        return meta

    def delete(self, case_id: str) -> None:
        shutil.rmtree(self._dir(case_id))
