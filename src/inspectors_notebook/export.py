"""Exports a case as plain text (default), Markdown or HTML (FR-27), and pinned
screenshots as a zip whose file names match the timeline entries (FR-28).

Exports run in time order, the way tickets read. Key findings (starred items) come
first. Each query shows its text, a summary line built from the data, and up to a few
relevant rows (Export content design, level 3). Everything from consoles and logs is
escaped in HTML.
"""

import html
import zipfile
from dataclasses import dataclass
from datetime import timezone, tzinfo
from pathlib import Path

from . import timeline
from .rules import KEEP
from .timeline import Item

CONSOLE_NAMES = {"defender": "Defender XDR", "sentinel": "Sentinel"}
TAGS = {"page": "PAGE", "query": "QUERY", "note": "NOTE", "screenshot": "SHOT", "result": "RESULT"}
TAG_WIDTH = 9  # INCIDENT plus a space
INDENT = " " * (7 + TAG_WIDTH)  # under the text after "HH:MM  TAG      "
CELL_WIDTH = 60


@dataclass
class Options:
    fmt: str = "text"  # text, markdown or html
    findings: bool = True
    timeline: bool = True
    rows: bool = True
    notes: bool = True
    hidden: bool = False  # also include hidden events and those awaiting review
    screenshots: bool = True
    row_limit: int = 5
    utc: bool = False
    tz: tzinfo | None = None


# What goes in


def included(items: list[Item], opts: Options) -> list[Item]:
    out = []
    for item in items:
        if item.disposition != KEEP and not opts.hidden and not item.star:
            continue
        if item.kind == "note" and not opts.notes:
            continue
        if item.kind == "screenshot" and not (opts.screenshots and item.pinned):
            continue
        out.append(item)
    return out


def screenshot_name(item: Item, tz: tzinfo | None = None) -> str:
    moment = timeline.parse_time(item.ts)
    stamp = moment.astimezone(tz).strftime("%H%M") if moment else "0000"
    return f"{stamp}-{item.ids[0]:04d}-{item.trigger or 'screenshot'}.webp"


def tag(item: Item) -> str:
    if item.kind == "record":
        return item.label.split(" ")[0].upper()
    return TAGS.get(item.kind, item.kind.upper())


def headline(item: Item, entities: list[str], opts: Options) -> str:
    """One line per item: what the analyst would write in a ticket."""
    if item.kind == "record":
        return f"{item.label}: {item.text}" if item.text else item.label
    if item.kind == "query":
        return f"{item.label} ({item.language})" if item.language else item.label
    if item.kind == "note":
        return item.text
    if item.kind == "screenshot":
        return f"[screenshot {screenshot_name(item, opts.tz)}]"
    return item.text or item.label


def entry_line(item: Item, entities: list[str], opts: Options) -> str:
    """The headline for formats without a tag column: notes say they are notes."""
    line = headline(item, entities, opts)
    return f"Note: {line}" if item.kind == "note" else line


def finding_line(item: Item, entities: list[str], opts: Options) -> str:
    if item.annotation:
        return item.annotation
    if item.kind == "query" and item.result:
        first = item.code.splitlines()[0] if item.code else item.label
        return f"{first}: {timeline.summary_line(item.result, entities, opts.tz, opts.utc)}"
    return headline(item, entities, opts)


def row_table(item: Item, entities: list[str], opts: Options) -> tuple[list[str], list[list[str]]]:
    """Header and cell text for the relevant rows of a query, or nothing."""
    if not (opts.rows and item.result and opts.row_limit > 0):
        return [], []
    rows = timeline.relevant_rows(item.result, entities, opts.row_limit)
    if not rows:
        return [], []
    columns = item.result.get("columns") or []
    chosen = timeline.choose_columns(columns, rows, entities)
    t = timeline.time_column(columns)

    def cell(row, i):
        value = row[i] if i < len(row) else ""
        if i == t:
            return timeline.clock(value, opts.tz)
        text = " ".join(str("" if value is None else value).split())
        return text if len(text) <= CELL_WIDTH else text[: CELL_WIDTH - 3] + "..."

    return [columns[i] for i in chosen], [[cell(r, i) for i in chosen] for r in rows]


def header(case: dict, opts: Options) -> tuple[list[str], list[str], str]:
    """The case's name parts, its details (tenant, console) and when it started."""
    title = case.get("title") or "Untitled case"
    name = [f"Incident {case['incidentId']}", title] if case.get("incidentId") else [title]
    details = [f"Tenant: {case['tenant']}" if case.get("tenant") else "", CONSOLE_NAMES.get(case.get("console"), case.get("console") or "")]
    started = timeline.parse_time(case.get("created"))
    when = ""
    if started:
        when = f"Case started {started.astimezone(opts.tz):%d/%m/%Y %H:%M}"
        if opts.utc:
            when += f" ({started.astimezone(timezone.utc):%H:%M} UTC)"
    return name, [d for d in details if d], when


# Formats


def render(case: dict, items: list[Item], opts: Options) -> str:
    entities = case.get("entities") or []
    chosen = included(items, opts)
    findings = [i for i in chosen if i.star] if opts.findings else []
    return {"text": _text, "markdown": _markdown, "html": _html}[opts.fmt](case, chosen, findings, entities, opts)


def _text(case, items, findings, entities, opts) -> str:
    name, details, when = header(case, opts)
    out = [" | ".join(name + details)] + ([when] if when else []) + [""]
    if findings:
        out.append("KEY FINDINGS")
        out += [f"{timeline.clock(i.ts, opts.tz, opts.utc)}  {finding_line(i, entities, opts)}" for i in findings]
        out.append("")
    if opts.timeline:
        out += ["TIMELINE", ""]
        for item in items:
            out.append(f"{timeline.clock(item.ts, opts.tz, opts.utc)}  {tag(item):<{TAG_WIDTH}}{headline(item, entities, opts)}")
            if item.kind == "query":
                out += [INDENT + line for line in item.code.splitlines()]
            if item.result:
                out.append(f"{INDENT}Result: {timeline.summary_line(item.result, entities, opts.tz, opts.utc)}")
                _, cells = row_table(item, entities, opts)
                out += [INDENT + "  ".join(c for c in row if c) for row in cells]
            if item.annotation:
                out.append(f"{INDENT}Comment: {item.annotation}")
    return "\n".join(out).rstrip() + "\n"


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|")


def _markdown(case, items, findings, entities, opts) -> str:
    name, details, when = header(case, opts)
    out = [f"# {': '.join(name)}", ""]
    meta = details + ([when] if when else [])
    if meta:
        out += [" · ".join(meta), ""]
    if findings:
        out += ["## Key findings", ""]
        out += [f"- **{timeline.clock(i.ts, opts.tz, opts.utc)}** {finding_line(i, entities, opts)}" for i in findings]
        out.append("")
    if opts.timeline:
        out += ["## Timeline", ""]
        for item in items:
            out.append(f"- **{timeline.clock(item.ts, opts.tz, opts.utc)}** {entry_line(item, entities, opts)}")
            if item.kind == "query":
                out += ["", f"  ```{(item.language or '').lower()}"] + [f"  {line}" for line in item.code.splitlines()] + ["  ```"]
            if item.result:
                out += ["", f"  Result: {timeline.summary_line(item.result, entities, opts.tz, opts.utc)}"]
                columns, cells = row_table(item, entities, opts)
                if cells:
                    out += ["", "  | " + " | ".join(map(_md_cell, columns)) + " |", "  |" + " --- |" * len(columns)]
                    out += ["  | " + " | ".join(map(_md_cell, row)) + " |" for row in cells]
            if item.annotation:
                out += ["", f"  Comment: {item.annotation}"]
            if item.kind == "query" or item.result or item.annotation:
                out.append("")
    return "\n".join(out).rstrip() + "\n"


def _html(case, items, findings, entities, opts) -> str:
    e = html.escape
    name, details, when = header(case, opts)
    first = ": ".join(name)
    out = [
        "<!doctype html>",
        '<html lang="en-GB">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{e(first)}</title>",
        "<style>body{font-family:'Segoe UI',system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;color:#15191E}"
        "pre,code,td{font-family:Consolas,monospace;font-size:0.9em}pre{background:#F1F3F5;padding:0.5rem;overflow:auto}"
        "table{border-collapse:collapse}td,th{border:1px solid #DDE1E6;padding:0.2rem 0.4rem;text-align:left}"
        "time{font-family:Consolas,monospace;color:#56606B;margin-right:0.5rem}</style>",
        "</head>",
        "<body>",
        f"<h1>{e(first)}</h1>",
    ]
    meta = details + ([when] if when else [])
    if meta:
        out.append(f"<p>{e(' · '.join(meta))}</p>")
    if findings:
        out += ["<h2>Key findings</h2>", "<ul>"]
        out += [f"<li><time>{e(timeline.clock(i.ts, opts.tz, opts.utc))}</time>{e(finding_line(i, entities, opts))}</li>" for i in findings]
        out.append("</ul>")
    if opts.timeline:
        out += ["<h2>Timeline</h2>", "<ol>"]
        for item in items:
            out.append(f"<li><time>{e(timeline.clock(item.ts, opts.tz, opts.utc))}</time>{e(entry_line(item, entities, opts))}")
            if item.kind == "query":
                out.append(f"<pre><code>{e(item.code)}</code></pre>")
            if item.result:
                out.append(f"<p>Result: {e(timeline.summary_line(item.result, entities, opts.tz, opts.utc))}</p>")
                columns, cells = row_table(item, entities, opts)
                if cells:
                    out.append("<table><tr>" + "".join(f"<th>{e(h)}</th>" for h in columns) + "</tr>")
                    out += ["<tr>" + "".join(f"<td>{e(c)}</td>" for c in row) + "</tr>" for row in cells]
                    out.append("</table>")
            if item.annotation:
                out.append(f"<p>Comment: {e(item.annotation)}</p>")
            out.append("</li>")
        out.append("</ol>")
    out += ["</body>", "</html>"]
    return "\n".join(out) + "\n"


# Screenshots (FR-28)


def screenshot_files(case_dir: Path, items: list[Item], tz: tzinfo | None = None) -> list[tuple[str, Path]]:
    return [
        (screenshot_name(i, tz), case_dir / i.file)
        for i in items
        if i.kind == "screenshot" and i.pinned and i.file and (case_dir / i.file).is_file()
    ]


def write_zip(destination: Path, files: list[tuple[str, Path]]) -> int:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as z:  # WebP is already compressed
        for name, path in files:
            z.write(path, arcname=name)
    return len(files)
