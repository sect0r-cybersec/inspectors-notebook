"""The case lifecycle (FR-1, FR-3, FR-6 to FR-8, FR-21, FR-24).

One case records at a time. Every captured event goes into an in-memory pre-roll
buffer (never written to disk); during a case it is also stored with the rules'
decision. Start detection suggests a case after the analyst dwells on an incident page
and then pivots; it needs the console parsers' incident URL patterns to fire.
"""

import re
import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable

from . import rules
from .case_store import CaseStore
from .rules import KEEP, CaseContext, Decision

PREROLL_SECONDS = 180  # FR-6
DWELL_SECONDS = 30  # FR-3
IDLE_SECONDS = 300  # FR-18: events captured after this long without input are hidden


def local_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]+", "-", text).strip("-")[:40]


class CaseManager:
    def __init__(
        self,
        store: CaseStore,
        on_change: Callable[[], None] = lambda: None,
        clock: Callable[[], float] = time.monotonic,
        idle_seconds: Callable[[], float] = lambda: 0.0,
        now: Callable[[], str] = local_now,
    ):
        self._store = store
        self._on_change = on_change
        self._clock = clock
        self._idle_seconds = idle_seconds
        self._now = now
        self._lock = threading.RLock()
        self._preroll: deque[tuple[float, dict]] = deque()
        self._case: dict | None = None
        self._events: list[dict] = []
        self._decisions: list[Decision] = []
        self._marks: dict[int, dict] = {}  # per event: disposition, star, annotation, pin
        self._context = CaseContext()
        self._paused = False
        self._elapsed = 0.0
        self._running_since: float | None = None
        self._dwell: dict | None = None
        self._suggestion: dict | None = None
        self._dismissed: set[tuple] = set()

    # State

    @property
    def recording(self) -> bool:
        with self._lock:
            return self._case is not None and not self._paused

    def summary(self) -> dict:
        with self._lock:
            case = None
            if self._case:
                counts = {"keep": 0, "review": 0, "hide": 0}
                for d in self._decisions:
                    counts[d.disposition] += 1
                elapsed = self._elapsed + (self._clock() - self._running_since if self._running_since else 0)
                case = {
                    **{k: self._case.get(k) for k in ("id", "incidentId", "console", "title", "entities", "tenant")},
                    "state": "paused" if self._paused else "recording",
                    "elapsedSeconds": int(elapsed),
                    "counts": counts,
                    "suggestedEntities": rules.suggested_entities(self._events, self._decisions, self._case["entities"])[:6],
                }
            return {"case": case, "suggestion": self._suggestion}

    def events(self) -> list[tuple[dict, Decision]]:
        with self._lock:
            return list(zip(self._events, self._decisions))

    # Capture

    def ingest(self, event: dict) -> None:
        """A capture event from a browser (page visit, query or result)."""
        changed = False
        with self._lock:
            now = self._clock()
            idle = self._idle_seconds() >= IDLE_SECONDS
            item = {k: v for k, v in event.items() if k != "type"}
            item["idle"] = idle
            if self._case is None:
                # The pre-roll holds what happened before a case starts, so only fill it then.
                self._preroll.append((now, item))
                while self._preroll and now - self._preroll[0][0] > PREROLL_SECONDS:
                    self._preroll.popleft()
                changed = self._detect_start(item, now)
            else:
                changed = self._detect_switch(item)
                if not self._paused:
                    self._record(item)
                    changed = True
        if changed:
            self._on_change()

    def add_screenshot(self, request: dict, webp: bytes, width: int, height: int) -> bool:
        with self._lock:
            if not self.recording:
                return False
            item = {k: request.get(k) for k in ("source", "seq", "ts", "console", "tabId", "url", "title", "trigger")}
            item.update(kind="screenshot", idle=False, width=width, height=height)
            event_id = len(self._events) + 1
            item["file"] = self._store.save_screenshot(self._case["id"], event_id, webp)
            self._record(item)
        self._on_change()
        return True

    def _record(self, item: dict) -> None:
        item = {**item, "id": len(self._events) + 1}
        if self._case.get("tenant") is None and item.get("tenant"):
            self._case["tenant"] = self._context.tenant = item["tenant"]
        decision = rules.decide(item, self._context, idle=item.get("idle", False), manual=self._disposition(item["id"]))
        self._remember(item, decision)
        self._events.append(item)
        self._decisions.append(decision)
        self._store.append_event(self._case["id"], item)
        self._case["lastActivity"] = item.get("ts") or self._now()
        self._store.save_meta(self._case)

    def _disposition(self, event_id: int) -> str | None:
        return self._marks.get(event_id, {}).get("disposition")

    def _remember(self, item: dict, decision: Decision) -> None:
        """Kept pages and queries make later identical ones duplicates (FR-18)."""
        if decision.disposition != KEEP:
            return
        if item.get("kind") == "page_visit":
            self._context.kept_pages.add(rules.page_key(item))
        elif item.get("kind") == "query":
            self._context.kept_queries.add(rules.query_key(item))

    def _rerun(self) -> None:
        """Apply the rules again from the start, after the entities or a decision changed (FR-21)."""
        self._context = CaseContext(entities=list(self._case["entities"]), tenant=self._case.get("tenant"))
        self._decisions = []
        for item in self._events:
            decision = rules.decide(item, self._context, idle=item.get("idle", False), manual=self._disposition(item["id"]))
            self._remember(item, decision)
            self._decisions.append(decision)

    # Start detection (FR-3, FR-7, FR-8)

    def _detect_start(self, item: dict, now: float) -> bool:
        if item.get("kind") == "page_visit" and item.get("incidentId"):
            key = (item.get("console"), item["incidentId"])
            if not self._dwell or self._dwell["key"] != key:
                self._dwell = {"key": key, "title": item.get("title"), "since": now}
            return False
        dwell = self._dwell
        if not dwell or dwell["key"] in self._dismissed or now - dwell["since"] < DWELL_SECONDS:
            return False
        if item.get("kind") not in ("query", "page_visit"):
            return False
        console, incident = dwell["key"]
        self._suggestion = {
            "kind": "start",
            "console": console,
            "incidentId": incident,
            "title": dwell["title"],
            "resume": self._store.find_by_incident(console, incident) is not None,
        }
        self._dwell = None
        return True

    def _detect_switch(self, item: dict) -> bool:
        incident = item.get("incidentId")
        if item.get("kind") != "page_visit" or not incident:
            return False
        key = (item.get("console"), incident)
        if key == (self._case.get("console"), self._case.get("incidentId")) or key in self._dismissed:
            return False
        self._suggestion = {"kind": "switch", "console": key[0], "incidentId": incident, "title": item.get("title")}
        return True

    def accept_suggestion(self) -> None:
        with self._lock:
            s = self._suggestion
            if not s:
                return
            if s["kind"] == "switch" and self._case:
                self._stop()
            self._start(incident_id=s["incidentId"], console=s["console"], title=s.get("title") or "")
        self._on_change()

    def dismiss_suggestion(self) -> None:
        with self._lock:
            if self._suggestion:
                self._dismissed.add((self._suggestion["console"], self._suggestion["incidentId"]))
                self._suggestion = None
        self._on_change()

    # Lifecycle (FR-1)

    def start(self, incident_id: str | None = None, title: str = "", entities=(), console: str | None = None) -> str:
        with self._lock:
            if self._case:
                self._stop()
            case_id = self._start(incident_id, console, title, entities)
        self._on_change()
        return case_id

    def _start(self, incident_id=None, console=None, title="", entities=()) -> str:
        incident_id = (incident_id or "").strip() or None
        existing = self._store.find_by_incident(console, incident_id) if incident_id else None
        if existing:  # FR-7: reopening a known incident resumes its case
            meta, events, marks = self._store.load(existing)
            meta["entities"] = list(dict.fromkeys(meta.get("entities", []) + list(entities)))
            self._case, self._events, self._marks = meta, events, marks
        else:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            base = f"{stamp}-{_slug(incident_id)}" if incident_id else stamp
            case_id, n = base, 1
            while (self._store.root / case_id).exists():  # two cases started in the same second
                n += 1
                case_id = f"{base}-{n}"
            self._case = {
                "id": case_id,
                "incidentId": incident_id,
                "console": console,
                "title": title.strip(),
                "entities": [e.strip() for e in entities if e.strip()],
                "tenant": None,
                "created": self._now(),
                "lastActivity": self._now(),
                "exported": False,
                "pinned": False,
            }
            self._store.create(self._case)
            self._events, self._marks = [], {}
        self._rerun()
        self._suggestion = None
        self._dwell = None
        self._paused = False
        self._elapsed = 0.0
        self._running_since = self._clock()
        for item in self._linked_preroll():
            self._record(item)
        self._store.save_meta(self._case)
        return self._case["id"]

    def _linked_preroll(self) -> list[dict]:
        """Buffered events linked to the case (FR-6): from the first visit to its incident
        page onwards, plus any earlier event that mentions a case entity."""
        incident = self._case.get("incidentId")
        now = self._clock()
        items = [item for t, item in self._preroll if now - t <= PREROLL_SECONDS]
        start = next(
            (i for i, it in enumerate(items) if incident and it.get("incidentId") == incident and it.get("kind") == "page_visit"),
            len(items),
        )
        before = [it for it in items[:start] if rules.matching_entities(it, self._case["entities"])]
        self._preroll.clear()  # each buffered event joins at most one case
        return before + items[start:]

    def pause(self) -> None:
        with self._lock:
            if self._case and not self._paused:
                self._elapsed += self._clock() - self._running_since
                self._running_since = None
                self._paused = True
        self._on_change()

    def resume(self) -> None:
        with self._lock:
            if self._case and self._paused:
                self._running_since = self._clock()
                self._paused = False
        self._on_change()

    def stop(self) -> None:
        with self._lock:
            self._stop()
        self._on_change()

    def _stop(self) -> None:
        if not self._case:
            return
        self._case["lastActivity"] = self._now()
        self._store.save_meta(self._case)
        self._case, self._events, self._decisions, self._marks = None, [], [], {}
        self._context = CaseContext()
        self._paused, self._running_since, self._elapsed = False, None, 0.0
        self._suggestion = None

    # Entities and decisions (FR-21, FR-24)

    def add_entity(self, value: str) -> None:
        with self._lock:
            value = value.strip()
            if not self._case or not value or value.lower() in (e.lower() for e in self._case["entities"]):
                return
            self._case["entities"].append(value)
            self._store.save_meta(self._case)
            self._rerun()
        self._on_change()

    def remove_entity(self, value: str) -> None:
        with self._lock:
            if not self._case or value not in self._case["entities"]:
                return
            self._case["entities"].remove(value)
            self._store.save_meta(self._case)
            self._rerun()
        self._on_change()

    def set_decision(self, event_id: int, disposition: str | None) -> None:
        """Keep or hide one event; None restores the rules' decision (FR-24)."""
        if disposition not in (rules.KEEP, rules.HIDE, None):
            raise ValueError(disposition)
        self._mark(event_id, "disposition", disposition, rerun=True)

    def set_star(self, event_id: int, starred: bool) -> None:
        """Mark an event as a finding; findings lead the export."""
        self._mark(event_id, "star", bool(starred))

    def set_annotation(self, event_id: int, text: str) -> None:
        self._mark(event_id, "annotation", str(text).strip()[:2000])

    def set_pin(self, event_id: int, pinned: bool) -> None:
        """Include a screenshot in the export (FR-26)."""
        self._mark(event_id, "pin", bool(pinned))

    def _mark(self, event_id: int, field: str, value, rerun: bool = False) -> None:
        with self._lock:
            if not self._case or not 1 <= event_id <= len(self._events):
                return
            marks = self._marks.setdefault(event_id, {})
            if value in (None, False, ""):
                marks.pop(field, None)
            else:
                marks[field] = value
            self._store.append_action(self._case["id"], event_id, field, value)
            if rerun:
                self._rerun()
        self._on_change()

    def add_note(self, text: str) -> None:
        """A timestamped free-text note in the timeline (FR-25)."""
        text = str(text).strip()
        with self._lock:
            if not self._case or not text:
                return
            self._record({"kind": "note", "text": text[:4000], "ts": self._now(), "idle": False})
        self._on_change()

    def marks(self) -> dict[int, dict]:
        with self._lock:
            return {k: dict(v) for k, v in self._marks.items()}

    def case_meta(self) -> dict | None:
        with self._lock:
            return dict(self._case) if self._case else None

    def mark_exported(self) -> None:
        """Remember the case was exported, so the cache does not warn about it (FR-32)."""
        with self._lock:
            if not self._case:
                return
            self._case["exported"] = True
            self._case["exportedAt"] = self._now()
            self._store.save_meta(self._case)
        self._on_change()
