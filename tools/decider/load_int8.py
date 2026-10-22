"""Loads the int8 checkpoint from convert_int8.py straight into a decider engine.

The torso is built on the meta device (no memory), each linear layer is replaced by an
int8 dynamic-quantised one filled from linear.safetensors, and every other tensor is
assigned from other.safetensors one at a time, so no full-precision copy is ever made:
about 3 GB in memory instead of 8.

Reads local files only; nothing is downloaded.
"""

import json
import os

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import torch  # noqa: E402
import transformers  # noqa: E402
from safetensors import safe_open  # noqa: E402
from strands_decider.infer import EngineConfig, SystemOneEngine  # noqa: E402
from strands_decider.modeling import (  # noqa: E402
    StrandsDeciderConfig,
    StrandsDeciderModel,
    build_head,
    config_path,
    ensure_bos,
    load_head_state,
)

QLinear = torch.ao.nn.quantized.dynamic.Linear


def _split(name: str) -> tuple[str, str]:
    parent, _, attr = name.rpartition(".")
    return parent, attr


def load_int8_engine(path: str) -> SystemOneEngine:
    with open(os.path.join(path, "int8.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    config = StrandsDeciderConfig.from_json(config_path(path))
    tok = transformers.AutoTokenizer.from_pretrained(path)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    if config.force_bos:
        ensure_bos(tok)

    text = dict(manifest["text_config"])
    text_cfg = transformers.AutoConfig.for_model(text.pop("model_type"), **text)
    text_cfg._attn_implementation = "sdpa"  # what from_pretrained picks for this model on CPU
    with torch.device("meta"):
        torso = transformers.Qwen3_5ForCausalLM(text_cfg).model

    with safe_open(os.path.join(path, "linear.safetensors"), framework="pt") as f:
        for name, spec in manifest["linear"].items():
            q = QLinear(spec["in"], spec["out"], bias_=spec["bias"], dtype=torch.qint8)
            weight = torch._make_per_tensor_quantized_tensor(f.get_tensor(f"{name}.weight"), spec["scale"], spec["zero_point"])
            q.set_weight_bias(weight, f.get_tensor(f"{name}.bias") if spec["bias"] else None)
            parent, attr = _split(name)
            setattr(torso.get_submodule(parent), attr, q)

    with safe_open(os.path.join(path, "other.safetensors"), framework="pt") as f:
        for name in f.keys():
            parent, attr = _split(name)
            module = torso.get_submodule(parent)
            tensor = f.get_tensor(name)
            if attr in module._parameters:
                module._parameters[attr] = torch.nn.Parameter(tensor, requires_grad=False)
            else:
                module._buffers[attr] = tensor

    left = [n for n, t in list(torso.named_parameters()) + list(torso.named_buffers()) if t.is_meta]
    if left:
        raise RuntimeError(f"not loaded: {left[:5]}")

    model = StrandsDeciderModel.__new__(StrandsDeciderModel)
    torch.nn.Module.__init__(model)
    model.config = config
    model.torso = torso
    model.tokenizer = tok
    model.head = build_head(config, StrandsDeciderModel.hidden_size(torso))
    model.head.load_state_dict(load_head_state(path))
    model.head.to(torch.float32)
    return SystemOneEngine(model, EngineConfig(device="cpu"))
