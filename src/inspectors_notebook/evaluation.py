"""The Gate 2 eval set: does the model beat plain entity matching on lab cases? (S7)

    inspectors-notebook-eval cases
    inspectors-notebook-eval export <case id> <sheet.csv>
    inspectors-notebook-eval build <sheet.csv>... --out evalset.jsonl
    inspectors-notebook-eval score evalset.jsonl [predictions.jsonl]...

1. Record investigations in the lab with Inspector, as usual.
2. `export` writes one row per timeline item to a CSV sheet. Mark each row relevant to the
   case or not (y or n), and notable or not. Your Keep, Hide and stars from the panel are
   filled in already; a blank row is left out of the eval set.
3. `build` joins the labels with the cases into `evalset.jsonl`. Each line holds the model's
   input for that item, exactly as the app would send it: the case header and one event.
4. A model runner reads the eval set and writes one prediction per line:
   {"key": ..., "relevant": 0.0 to 1.0, "notable": 0.0 to 1.0 or null}
5. `score` compares plain entity matching, the current rules and each model.

Eval sets come from the purple team lab only, never from client data.
"""

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from . import rules, timeline
from .case_store import CaseStore, default_root
from .rules import HIDE, KEEP, REVIEW, CaseContext

FORMAT = 1
LABELLED_KINDS = ("record", "page", "query", "result", "window", "desktop")  # notes and screenshots are the analyst's own
COLUMNS = ["key", "time", "kind", "event", "entity_match", "rules", "relevant", "notable", "comment"]
STATE_LIMIT = 1200  # characters; keeps the model's input near FR-22's 150 to 250 tokens
REVIEW_BAND = (0.3, 0.7)  # MJ-5: borderline scores go to review, never straight to hidden
MAX_REVIEW_SHARE = 0.2  # proposed: a model that sends everything to review saves the analyst nothing
CONSOLE_NAMES = {"defender": "Defender", "sentinel": "Sentinel"}


# The model's input


def case_header(meta: dict) -> str:
    title = meta.get("title") or "Untitled case"
    incident = f" (incident {meta['incidentId']})" if meta.get("incidentId") else ""
    entities = ", ".join(meta.get("entities") or []) or "none yet"
    return f"Case: {title}{incident}. Entities: {entities}."


def event_summary(item: timeline.Item) -> str:
    """One timeline item as plain text, as the model reads it."""
    if item.kind in ("record", "page"):
        return f"Page visit: {item.url}, title '{item.text}'."
    if item.kind in ("query", "result"):
        console = CONSOLE_NAMES.get(item.console or "", item.console or "console")
        text = f"{item.label} ({console}): {item.code}." if item.kind == "query" else f"Results ({console})."
        if item.result:
            text += f" Result: {timeline.summary_line(item.result, [])}."
            rows, columns = item.result.get("rows") or [], item.result.get("columns") or []
            if rows:
                text += " First row: " + ", ".join(f"{c}={v}" for c, v in zip(columns, rows[0]))
        return text
    if item.kind == "window":
        return f"Switched to {item.label}: '{item.text}'."
    if item.kind == "desktop":
        return f"Text on screen in {item.label}, window '{item.text}':\n{item.code}"
    return f"{item.label}: {item.text}"


def model_state(meta: dict, item: timeline.Item) -> str:
    return f"{case_header(meta)}\nEvent: {event_summary(item)}"[:STATE_LIMIT]


# Items from a case


@dataclass
class EvalItem:
    key: str
    item: timeline.Item
    entity_match: bool
    rules: str  # the rules' decision without the analyst's Keep or Hide


def case_items(store: CaseStore, case_id: str) -> tuple[dict, list[EvalItem], dict[int, dict]]:
    meta, events, marks = store.load(case_id)
    entities = meta.get("entities") or []
    decisions = rules.decide_all(events, CaseContext(entities=list(entities), tenant=meta.get("tenant")))
    items = timeline.build(events, decisions, marks)
    by_id = {e["id"]: e for e in events}
    out = []
    for item in items:
        if item.kind not in LABELLED_KINDS:
            continue
        matched = any(rules.matching_entities(by_id[i], entities) for i in item.ids)
        out.append(EvalItem(f"{case_id}:{item.ids[0]}", item, matched, item.disposition))
    return meta, out, marks


# Labelling sheets


def _cell(value) -> str:
    """CSV text that a spreadsheet will not run: event text can come from attacker-controlled logs."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t") else text


def export_sheet(store: CaseStore, case_id: str, path: Path) -> int:
    meta, items, marks = case_items(store, case_id)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:  # the BOM makes Excel read UTF-8
        out = csv.writer(f)
        out.writerow(COLUMNS)
        for e in items:
            first = marks.get(e.item.ids[0], {})
            relevant = {KEEP: "y", HIDE: "n"}.get(first.get("disposition"), "")
            notable = "y" if first.get("star") else ""
            row = [e.key, e.item.ts, e.item.kind, event_summary(e.item), "y" if e.entity_match else "n", e.rules, relevant, notable, first.get("annotation", "")]
            out.writerow([_cell(v) for v in row])
    return len(items)


def _answer(text: str, key: str, column: str) -> bool | None:
    value = text.strip().lower()
    if value in ("", "?"):
        return None
    if value in ("y", "yes"):
        return True
    if value in ("n", "no"):
        return False
    raise ValueError(f"{key}: {column} must be y or n, not {text!r}")


def build(store: CaseStore, sheets: list[Path]) -> list[dict]:
    lines, cases = [], {}
    for sheet in sheets:
        with open(sheet, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                key = row["key"].strip()
                relevant = _answer(row.get("relevant", ""), key, "relevant")
                if relevant is None:
                    continue
                case_id = key.rpartition(":")[0]
                if case_id not in cases:
                    meta, items, _ = case_items(store, case_id)
                    cases[case_id] = (meta, {e.key: e for e in items})
                meta, items = cases[case_id]
                if key not in items:
                    raise ValueError(f"{key}: not an item in case {case_id}")
                e = items[key]
                lines.append({
                    "format": FORMAT,
                    "key": key,
                    "case": {k: meta.get(k) for k in ("id", "title", "incidentId", "entities")},
                    "kind": e.item.kind,
                    "state": model_state(meta, e.item),
                    "entity_match": e.entity_match,
                    "rules": e.rules,
                    "relevant": relevant,
                    "notable": _answer(row.get("notable", ""), key, "notable"),
                })
    return lines


# Scoring


def model_decision(entity_match: bool, relevant: float) -> str:
    """Entity match always keeps (FR-19); otherwise the model's tie-break, with a review band (MJ-5)."""
    if entity_match:
        return KEEP
    low, high = REVIEW_BAND
    return KEEP if relevant >= high else HIDE if relevant <= low else REVIEW


def metrics(pairs: list[tuple[bool, str]]) -> dict:
    """pairs: (labelled relevant, decision). Review counts as not hidden: the analyst still sees it."""
    relevant = [d for r, d in pairs if r]
    shown = [r for r, d in pairs if d != HIDE]
    tp = sum(shown)
    precision = tp / len(shown) if shown else 0.0
    recall = tp / len(relevant) if relevant else 0.0
    return {
        "items": len(pairs),
        "kept": sum(d == KEEP for _, d in pairs),
        "review": sum(d == REVIEW for _, d in pairs),
        "hidden": sum(d == HIDE for _, d in pairs),
        "evidence_lost": sum(d == HIDE for d in relevant),  # relevant items hidden
        "noise_kept": sum(not r and d == KEEP for r, d in pairs),
        "review_share": round(sum(d == REVIEW for _, d in pairs) / len(pairs), 3) if pairs else 0.0,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(2 * precision * recall / (precision + recall), 3) if precision + recall else 0.0,
    }


def score(evalset: list[dict], predictions: dict[str, dict[str, dict]]) -> dict:
    """Metrics per system: plain entity matching, the current rules, and each model."""
    systems = {
        "entity matching": [(e["relevant"], KEEP if e["entity_match"] else HIDE) for e in evalset],
        "rules": [(e["relevant"], e["rules"]) for e in evalset],
    }
    for name, preds in predictions.items():
        missing = [e["key"] for e in evalset if e["key"] not in preds]
        if missing:
            raise ValueError(f"{name}: no prediction for {missing[:3]}")
        systems[name] = [(e["relevant"], model_decision(e["entity_match"], preds[e["key"]]["relevant"])) for e in evalset]
    result = {name: metrics(pairs) for name, pairs in systems.items()}
    baseline = result["entity matching"]
    for name in predictions:
        m = result[name]
        # Gate 2 as proposed in docs/decisions.md: better F1, no more evidence lost, little review.
        m["gate2"] = (
            m["f1"] > baseline["f1"]
            and m["evidence_lost"] <= baseline["evidence_lost"]
            and m["review_share"] <= MAX_REVIEW_SHARE
        )
    return result


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# Command line


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="inspectors-notebook-eval", description="Build and score the Gate 2 eval set.")
    parser.add_argument("--cases", type=Path, default=None, help="case folder (default: Inspector's own)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("cases", help="list recorded cases")
    p = sub.add_parser("export", help="write a labelling sheet for one case")
    p.add_argument("case_id")
    p.add_argument("sheet", type=Path)
    p = sub.add_parser("build", help="join labelled sheets into an eval set")
    p.add_argument("sheets", type=Path, nargs="+")
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("score", help="compare entity matching, the rules and model predictions")
    p.add_argument("evalset", type=Path)
    p.add_argument("predictions", type=Path, nargs="*")
    args = parser.parse_args(argv)
    store = CaseStore(args.cases or default_root())

    if args.command == "cases":
        for meta in store.list():
            print(f"{meta['id']}  {meta.get('title') or 'Untitled case'}")
    elif args.command == "export":
        n = export_sheet(store, args.case_id, args.sheet)
        print(f"Wrote {n} items to {args.sheet}")
    elif args.command == "build":
        lines = build(store, args.sheets)
        with open(args.out, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        print(f"Wrote {len(lines)} labelled items to {args.out}")
    else:
        evalset = read_jsonl(args.evalset)
        predictions = {p.stem: {line["key"]: line for line in read_jsonl(p)} for p in args.predictions}
        result = score(evalset, predictions)
        print(f"{len(evalset)} items, {sum(e['relevant'] for e in evalset)} labelled relevant")
        header = f"{'system':24} {'kept':>5} {'review':>6} {'hidden':>6} {'lost':>5} {'noise':>5} {'review%':>7} {'prec':>6} {'recall':>6} {'F1':>6}  gate 2"
        print(header)
        for name, m in result.items():
            gate = {True: "pass", False: "fail"}.get(m.get("gate2"), "")
            print(f"{name:24} {m['kept']:>5} {m['review']:>6} {m['hidden']:>6} {m['evidence_lost']:>5} {m['noise_kept']:>5} "
                  f"{m['review_share']:>7.0%} {m['precision']:>6} {m['recall']:>6} {m['f1']:>6}  {gate}")


if __name__ == "__main__":
    main(sys.argv[1:])
