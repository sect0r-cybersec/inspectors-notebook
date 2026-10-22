# S7 Gate 2: labelling lab cases

Gate 2 asks whether the local model beats plain entity matching. The answer comes from your own lab investigations, labelled by you. Use the purple team lab only, never client data.

## 1. Record cases

Run investigations in the lab with Inspector recording, as you would at work: start a case, add the case entities, run your queries, visit enrichment sites, open tickets. Include the dead ends and unrelated tabs; the eval needs both relevant and irrelevant events. Aim for at least 10 cases and 200 labelled items, with plenty that name no case entity, because those are the only ones the model decides.

## 2. Export a labelling sheet per case

```bash
uv run inspectors-notebook-eval cases
```

```bash
uv run inspectors-notebook-eval export <case id> sheets/<case id>.csv
```

Open the CSV in Excel. One row per timeline item (a query and its result are one row). Notes and screenshots are left out: they are yours, not the model's to judge.

| Column | Meaning |
| --- | --- |
| `event` | What happened, as the model will read it |
| `entity_match` | Whether the item names a case entity (filled in) |
| `rules` | What the rules decided, ignoring your Keep and Hide (filled in) |
| `relevant` | **You:** `y` if this item belongs in the investigation's record, `n` if not |
| `notable` | **You:** `y` if it shows something that matters (a finding), `n` if routine |
| `comment` | Optional |

Your Keep or Hide from the panel pre-fills `relevant`, and a star pre-fills `notable`; check them. Leave a row blank to keep it out of the eval set. Cells that would start a spreadsheet formula are prefixed with `'`, since log text can be attacker-controlled.

## 3. Build the eval set

```bash
uv run inspectors-notebook-eval build sheets/*.csv --out evalset.jsonl
```

Each line holds the label and the model's input for that item: the case header and one event, as the app sends them.

## 4. Run the model and score

The model runs in its own environment (it needs torch, which the app does not depend on yet). It writes one line per item: `{"key": ..., "relevant": 0.0 to 1.0, "notable": 0.0 to 1.0 or null}`.

```bash
uv run inspectors-notebook-eval score evalset.jsonl int8-model.jsonl
```

The table compares plain entity matching, the current rules and each model:

| Column | Meaning |
| --- | --- |
| `lost` | Relevant items hidden: evidence the analyst would not see |
| `noise` | Irrelevant items kept |
| `review%` | Share of items sent to review (scores between 0.3 and 0.7) |
| `prec`, `recall`, `F1` | Against your `relevant` labels; review counts as shown |
| `gate 2` | The proposed criteria in `docs/decisions.md` |
