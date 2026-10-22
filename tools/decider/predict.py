"""Runs the int8 decider over an eval set and writes predictions for `inspectors-notebook-eval score`.

    python tools/decider/predict.py <int8 dir> <evalset.jsonl> <predictions.jsonl> [threads]

Offline: reads the int8 checkpoint and the eval set, writes predictions, sends nothing.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from load_int8 import load_int8_engine  # noqa: E402  (sets telemetry off and offline first)

import torch  # noqa: E402

int8_dir, evalset_path, out_path = sys.argv[1:4]
torch.set_num_threads(int(sys.argv[4]) if len(sys.argv) > 4 else 4)

MJ5 = {"type": "noul", "instructions": "Is this event part of the investigation of this case, even though it may not name a case entity?"}
MJ3 = {"type": "noul", "instructions": "Does this result show something notable for the investigation, rather than routine data?"}

engine = load_int8_engine(int8_dir)
items = [json.loads(line) for line in open(evalset_path, encoding="utf-8") if line.strip()]
times = []
with open(out_path, "w", encoding="utf-8") as out:
    for item in items:
        questions = {"relevant": MJ5}
        if item["kind"] in ("query", "result"):
            questions["notable"] = MJ3
        t = time.perf_counter()
        answers = engine.ask(item["state"], questions).answers
        times.append(time.perf_counter() - t)
        notable = answers["notable"].noul if "notable" in answers else None
        out.write(json.dumps({"key": item["key"], "relevant": answers["relevant"].noul, "notable": notable}) + "\n")
times.sort()
print(f"{len(items)} items, median {times[len(times) // 2]:.2f}s, max {times[-1]:.2f}s")
