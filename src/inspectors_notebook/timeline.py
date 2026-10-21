"""What the panel and the exports show: one item per action, built from the case's events.

A query and its results become one item. Summary lines are built from the data and
never invent anything (Export content design): "12 rows; 3 involve HOST-12; 09:14 to
09:31". The rows shown are the ones that name a case entity, capped, with at most six
of the most useful columns that are present.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, tzinfo

from .rules import HIDE, KEEP, REVIEW, Decision

MAX_COLUMNS = 6
TIME_COLUMNS = ("Timestamp", "TimeGenerated")
# Columns analysts pivot on, in order; only columns present in a result are used.
USEFUL_COLUMNS = (
    "DeviceName", "Computer", "AccountName", "AccountUpn", "UserPrincipalName", "InitiatingProcessAccountName",
    "ActionType", "FileName", "ProcessCommandLine", "InitiatingProcessFileName", "InitiatingProcessCommandLine",
    "RemoteIP", "RemoteUrl", "IPAddress", "SHA256",
)
QUERY_LABELS = {"defender": "Hunting query", "sentinel": "Logs query"}
_RANK = {KEEP: 0, REVIEW: 1, HIDE: 2}


@dataclass
class Item:
    ids: list[int]
    kind: str  # record, page, query, note, screenshot, result
    ts: str
    label: str
    text: str = ""
    code: str = ""
    language: str = ""
    console: str | None = None
    url: str = ""
    result: dict | None = None
    disposition: str = KEEP
    reason: str = ""
    flags: tuple = ()
    star: bool = False
    annotation: str = ""
    pinned: bool = False
    unlabelled: bool = False  # dropped from the labelling queue (FR-43)
    file: str = ""
    trigger: str = ""
    extra: dict = field(default_factory=dict)


# Times


def parse_time(value) -> datetime | None:
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d", value):
        return None
    text = re.sub(r"(\.\d{6})\d+", r"\1", value.replace("Z", "+00:00"))  # consoles send up to 7 digits
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def clock(value, tz: tzinfo | None = None, utc: bool = False) -> str:
    """HH:MM in local time, with the UTC time alongside when asked."""
    moment = parse_time(value)
    if not moment:
        return ""
    local = moment.astimezone(tz).strftime("%H:%M")
    return f"{local} ({moment.astimezone(timezone.utc):%H:%M} UTC)" if utc else local


# Results


def time_column(columns: list[str]) -> int | None:
    for name in TIME_COLUMNS:
        if name in columns:
            return columns.index(name)
    return None


def relevant_rows(result: dict, entities: list[str], limit: int) -> list[list]:
    """Rows naming a case entity, in result order (Export content design, level 3)."""
    rows = result.get("rows") or []
    patterns = [re.compile(r"(?<![\w-])" + re.escape(e) + r"(?![\w-])", re.I) for e in entities if e]
    if not patterns:
        return []
    picked = [r for r in rows if any(p.search(" ".join(map(str, r))) for p in patterns)]
    return picked[:limit]


def matched_entities(result: dict, entities: list[str]) -> list[str]:
    rows = result.get("rows") or []
    text = "\n".join(" ".join(map(str, r)) for r in rows)
    return [e for e in entities if e and re.search(r"(?<![\w-])" + re.escape(e) + r"(?![\w-])", text, re.I)]


def choose_columns(columns: list[str], rows: list[list], entities: list[str]) -> list[int]:
    """At most six: the time column, columns holding a case entity, then useful ones present."""
    chosen: list[int] = []
    t = time_column(columns)
    if t is not None:
        chosen.append(t)
    for i in range(len(columns)):
        if any(i < len(r) and any(e and e.lower() == str(r[i]).lower() for e in entities) for r in rows):
            if i not in chosen:
                chosen.append(i)
    for name in USEFUL_COLUMNS:
        if name in columns and columns.index(name) not in chosen:
            i = columns.index(name)
            if any(i < len(r) and r[i] not in (None, "") for r in rows):
                chosen.append(i)
    return chosen[:MAX_COLUMNS]


def summary_line(result: dict, entities: list[str], tz: tzinfo | None = None, utc: bool = False) -> str:
    if result.get("error"):
        return f"Failed: {result['error']}"
    count = result.get("rowCount")
    if count == 0:
        return "No results"
    if count is None:
        return "Results not read"
    parts = [f"{count} row{'s' if count != 1 else ''}"]
    involved = relevant_rows(result, entities, limit=10**9)
    if involved:
        parts.append(f"{len(involved)} involve {', '.join(matched_entities(result, entities))}")
    rows = result.get("rows") or []
    t = time_column(result.get("columns") or [])
    if t is not None:
        times = sorted(m for r in rows if t < len(r) and (m := parse_time(r[t])))
        if times:
            first, last = times[0], times[-1]
            span = f"{first.astimezone(tz):%H:%M} to {last.astimezone(tz):%H:%M}"
            if utc:
                span += f" ({first.astimezone(timezone.utc):%H:%M} to {last.astimezone(timezone.utc):%H:%M} UTC)"
            parts.append(span)
    if result.get("truncated"):
        parts.append("rows capped in this capture")
    return "; ".join(parts)


# Items


def _strongest(decisions: list[Decision]) -> Decision:
    analyst = [d for d in decisions if d.reason == "analyst"]
    return analyst[0] if analyst else min(decisions, key=lambda d: _RANK[d.disposition])


def build(events: list[dict], decisions: list[Decision], marks: dict[int, dict]) -> list[Item]:
    """Items in time order. A query's result joins the query's item."""
    items: list[Item] = []
    queries: dict[tuple, Item] = {}
    parts: dict[int, list[Decision]] = {}
    for event, decision in zip(events, decisions):
        kind = event.get("kind")
        key = (event.get("source"), event.get("tabId"), event.get("queryId"))
        if kind == "result" and key in queries:
            item = queries.pop(key)
            item.ids.append(event["id"])
            item.result = event
            parts[id(item)].append(decision)
            continue
        item = _item(event)
        if kind == "query":
            queries[key] = item
        parts[id(item)] = [decision]
        items.append(item)
    for item in items:
        d = _strongest(parts[id(item)])
        item.disposition, item.reason, item.flags = d.disposition, d.reason, d.flags
        first = marks.get(item.ids[0], {})
        item.star = bool(first.get("star"))
        item.annotation = first.get("annotation", "")
        item.pinned = bool(first.get("pin"))
        item.unlabelled = any(marks.get(i, {}).get("unlabelled") for i in item.ids)
    return items


def _item(event: dict) -> Item:
    kind = event.get("kind")
    common = {"ids": [event["id"]], "ts": event.get("ts") or "", "console": event.get("console"), "url": event.get("url") or ""}
    if kind == "page_visit" and event.get("incidentId"):
        record = (event.get("recordKind") or "incident").capitalize()
        return Item(kind="record", label=f"{record} {event['incidentId']}", text=event.get("title") or "", **common)
    if kind == "page_visit":
        return Item(kind="page", label="Page", text=event.get("title") or "", **common)
    if kind == "query":
        return Item(
            kind="query", label=QUERY_LABELS.get(event.get("console"), "Query"),
            code=str(event.get("query") or "").replace("\r\n", "\n").strip(), language=event.get("language") or "", **common,
        )
    if kind == "note":
        return Item(kind="note", label="Note", text=event.get("text") or "", **common)
    if kind == "screenshot":
        return Item(kind="screenshot", label="Screenshot", text=event.get("title") or "", file=event.get("file") or "",
                    trigger=event.get("trigger") or "", **common)
    if kind == "result":  # a result whose query was not captured
        return Item(kind="result", label="Results", result=event, **common)
    return Item(kind=str(kind), label=str(kind).capitalize(), **common)


def view(item: Item, entities: list[str], tz: tzinfo | None = None, utc: bool = False) -> dict:
    """An item as the panel shows it."""
    out = {
        "ids": item.ids, "kind": item.kind, "time": clock(item.ts, tz, utc), "label": item.label, "text": item.text,
        "code": item.code, "disposition": item.disposition, "reason": item.reason, "flags": list(item.flags),
        "star": item.star, "annotation": item.annotation, "pinned": item.pinned, "trigger": item.trigger,
        "unlabelled": item.unlabelled,
    }
    if item.result:
        out["summary"] = summary_line(item.result, entities, tz, utc)
        out["negative"] = item.result.get("rowCount") == 0
        out["suggest"] = [e["value"] for e in item.result.get("entities") or [] if isinstance(e, dict)][:3]
    return out


def counts(items: list[Item]) -> dict:
    tally = {"keep": 0, "review": 0, "hide": 0, "findings": 0}
    for item in items:
        tally[item.disposition] += 1
        tally["findings"] += item.star
    return tally
