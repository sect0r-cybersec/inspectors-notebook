# Decider tools (S7, outside the app)

Tools for measuring the local decision model, [strands-decider](https://github.com/strands-labs/strands-decider) 2B, before it can join the app. They have their own pinned requirements: torch, transformers and strands-decider are **not** dependencies of Inspector, and stay that way unless the model passes Gate 2 (`docs/decisions.md`).

| Script | What it does |
| --- | --- |
| `convert_int8.py` | One-off: merges the adapter into the base model, quantises every linear layer to int8, and saves safetensors files plus a JSON manifest (no pickle). Needs about 18 GB of memory for half a minute, so run it on a build machine. |
| `load_int8.py` | Loads that checkpoint without a full-precision copy: about 3 GB instead of 8. Used by the other two. |
| `predict.py` | Runs the int8 model over an eval set from `inspectors-notebook-eval build` and writes predictions for `inspectors-notebook-eval score`. |
| `bench.py` | Load time, memory and latency per request on CPU, for full precision or int8, at a chosen thread count. Synthetic events only. |

## Privacy

Nothing here sends captured or case data anywhere. Every script turns Hugging Face telemetry off, and loading the int8 checkpoint runs offline. The only network traffic is the model download from huggingface.co the first time `convert_int8.py` or a full-precision `bench.py` runs (about 4.8 GB).

Eval sets built from lab cases hold lab hostnames, accounts and queries. Keep them out of the repository unless you have reviewed them, as with the S3 fixtures.

## Set up

Use an environment of its own, outside the app's:

```bash
uv venv tools/decider/.venv --python 3.13
```

```bash
uv pip install --python tools/decider/.venv --require-hashes -r tools/decider/requirements.txt
```

`requirements.txt` pins the full tree with hashes, resolved for Windows and Python 3.13 from `requirements.in`. It was checked for LiteLLM on 22 October 2026: not present. Check again whenever it changes.

## Use

```bash
tools/decider/.venv/Scripts/python tools/decider/convert_int8.py int8
```

```bash
tools/decider/.venv/Scripts/python tools/decider/predict.py int8 evalset.jsonl int8-model.jsonl 4
```

```bash
uv run inspectors-notebook-eval score evalset.jsonl int8-model.jsonl
```

```bash
tools/decider/.venv/Scripts/python tools/decider/bench.py 4 bench.json int8
```

## Caveats

- Tied to strands-decider 0.2.0's internals (`SystemOneEngine`, `StrandsDeciderModel`) and the Qwen3.5 base; another version may need changes.
- Quantisation uses `torch.ao.quantization.quantize_dynamic`, which torch has deprecated in favour of torchao.
- int8 shifts the model's answers (mean 0.085, up to 0.26 on yes/no scores in the first measurement), so it is judged on Gate 2 by itself, not as a stand-in for full precision.
