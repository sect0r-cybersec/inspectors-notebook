"""One-off: turn the decider into an int8 checkpoint that loads without a full-precision copy.

    python tools/decider/convert_int8.py <out_dir>

Merges the LoRA adapter into the base weights, quantises every linear layer to int8
(dynamic quantisation: int8 weights, activations quantised per call), and writes:

- linear.safetensors: each linear layer's int8 weight and bias
- other.safetensors:  every other parameter and buffer, in float32
- int8.json:          per-layer shapes and quantisation parameters, plus the checkpoint it came from

No pickle: everything loads through safetensors and JSON. Needs about 18 GB of memory for
half a minute, so run it on a build machine; the first run downloads the model (about 4.8 GB).
"""

import json
import os
import shutil
import sys
import time

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import psutil  # noqa: E402
import torch  # noqa: E402
from safetensors.torch import save_file  # noqa: E402
from strands_decider.infer import load_engine  # noqa: E402
from strands_decider.modeling import checkpoint_dir  # noqa: E402

MODEL = "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610"
QLinear = torch.ao.nn.quantized.dynamic.Linear

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
proc = psutil.Process()
started = time.perf_counter()

engine = load_engine(MODEL, device="cpu")
with torch.inference_mode():
    merged = engine.model.torso.merge_and_unload()
    torso = torch.ao.quantization.quantize_dynamic(merged, {torch.nn.Linear}, dtype=torch.qint8)

linear, layers = {}, {}
for name, module in torso.named_modules():
    if isinstance(module, QLinear):
        w = module.weight()
        assert w.qscheme() == torch.per_tensor_affine, (name, w.qscheme())
        linear[f"{name}.weight"] = w.int_repr().contiguous()
        bias = module.bias()
        if bias is not None:
            linear[f"{name}.bias"] = bias.detach().float().contiguous()
        layers[name] = {
            "in": module.in_features, "out": module.out_features, "bias": bias is not None,
            "scale": float(w.q_scale()), "zero_point": int(w.q_zero_point()),
        }

quantised = tuple(f"{n}." for n in layers)
other = {}
for name, tensor in list(torso.named_parameters()) + list(torso.named_buffers()):
    if not name.startswith(quantised):
        other[name] = tensor.detach().float().contiguous()
persistent = {n for n, _ in torso.state_dict().items() if n in other}

save_file(linear, os.path.join(out, "linear.safetensors"))
save_file(other, os.path.join(out, "other.safetensors"))
source = checkpoint_dir(MODEL)
for keep in ("strands_decider_config.json", "tokenizer.json", "tokenizer_config.json", "chat_template.jinja", "head.safetensors", "LICENSE.md", "provenance.json"):
    if os.path.exists(os.path.join(source, keep)):
        shutil.copy(os.path.join(source, keep), out)
manifest = {
    "source": MODEL,
    "base_model": engine.model.config.base_model,
    "base_revision": engine.model.config.base_revision,
    "text_config": torso.config.to_dict(),
    "linear": layers,
    "non_persistent_buffers": sorted(set(other) - persistent),
    "torch": torch.__version__,
}
with open(os.path.join(out, "int8.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=1)

sizes = {f: round(os.path.getsize(os.path.join(out, f)) / 2**30, 2) for f in os.listdir(out) if f.endswith(".safetensors")}
print(json.dumps({
    "linear_layers": len(layers), "other_tensors": len(other), "files_gb": sizes,
    "convert_s": round(time.perf_counter() - started, 1),
    "convert_peak_gb": round(proc.memory_info().peak_wset / 2**30, 2),
}, indent=1))
