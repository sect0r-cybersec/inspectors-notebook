"""What each captured event is during a case: kept, for review, or hidden (FR-17 to FR-21).

Rules are deterministic and instant. Nothing is ever deleted: hidden events stay in the
case and can be restored (FR-24). Precedence, highest first:

1. The analyst's own keep or hide (FR-24).
2. Entity match: an event that mentions a case entity is kept (FR-19). No rule below
   can hide it, which stops attacker-controlled log text from steering it away later.
3. Hide (FR-18): captured while the analyst was idle, a navigation-only page, or a
   duplicate of something already kept.
4. From a different tenant than the case's: review, flagged (FR-14).
5. Otherwise a console event during a case is kept (FR-17); a query with no rows is
   kept as a negative finding (FR-20).
"""

import json
import re
from dataclasses import dataclass, field

KEEP, REVIEW, HIDE = "keep", "review", "hide"


@dataclass(frozen=True)
class Decision:
    disposition: str
    reason: str
    flags: tuple[str, ...] = ()
    matched: tuple[str, ...] = ()


@dataclass
class CaseContext:
    """What the rules need to know about the case."""

    entities: list[str] = field(default_factory=list)
    tenant: str | None = None
    kept_pages: set[str] = field(default_factory=set)
    kept_queries: set[tuple[str, int | None]] = field(default_factory=set)


def event_text(event: dict) -> str:
    """Everything an entity could appear in: URL, title, query, error, results."""
    parts = [event.get(k) for k in ("url", "title", "query", "error")]
    parts += [" ".join(map(str, event.get("columns") or []))]
    parts += [json.dumps(event.get("rows") or [], ensure_ascii=False)]
    parts += [e.get("value", "") for e in event.get("entities") or [] if isinstance(e, dict)]
    return "\n".join(str(p) for p in parts if p)


def _pattern(value: str) -> re.Pattern:
    # Whole values only: 10.0.0.1 must not match 10.0.0.12, nor HOST-1 match HOST-12.
    return re.compile(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])", re.IGNORECASE)


def matching_entities(event: dict, entities: list[str]) -> list[str]:
    text = event_text(event)
    return [e for e in entities if e and _pattern(e).search(text)]


def page_key(event: dict) -> str:
    return str(event.get("url") or "")


def query_key(event: dict) -> tuple[str, int | None]:
    return (" ".join(str(event.get("query") or "").split()), event.get("rowCount"))


def is_duplicate(event: dict, case: CaseContext) -> bool:
    """A page already kept in this case, or the same query with the same row count."""
    kind = event.get("kind")
    if kind == "page_visit":
        return page_key(event) in case.kept_pages
    if kind == "query":
        return query_key(event) in case.kept_queries
    return False


def decide(event: dict, case: CaseContext, *, idle: bool = False, manual: str | None = None) -> Decision:
    if manual in (KEEP, HIDE):
        return Decision(manual, "analyst")

    other_tenant = bool(event.get("tenant") and case.tenant and event["tenant"] != case.tenant)
    flags = ("other_tenant",) if other_tenant else ()

    matched = tuple(matching_entities(event, case.entities))
    if matched:
        return Decision(KEEP, "entity", flags, matched)

    if idle:
        return Decision(HIDE, "idle", flags)
    if event.get("kind") == "page_visit" and event.get("navigationOnly"):
        return Decision(HIDE, "navigation", flags)
    if is_duplicate(event, case):
        return Decision(HIDE, "duplicate", flags)

    if other_tenant:
        return Decision(REVIEW, "other_tenant", flags)

    if event.get("kind") == "result" and event.get("rowCount") == 0:
        return Decision(KEEP, "negative_finding", flags)
    return Decision(KEEP, "console", flags)


def suggested_entities(events: list[dict], decisions: list[Decision], case_entities: list[str]) -> list[str]:
    """Entities seen in kept events that are not case entities yet (FR-21)."""
    known = {e.lower() for e in case_entities}
    seen: list[str] = []
    for event, decision in zip(events, decisions):
        if decision.disposition != KEEP:
            continue
        for entity in event.get("entities") or []:
            value = entity.get("value") if isinstance(entity, dict) else None
            if value and value.lower() not in known and value not in seen:
                seen.append(value)
    return seen
