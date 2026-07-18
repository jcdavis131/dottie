"""Shared eval utilities: model/tokenizer loading, decode, logprob."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

from ava.config import AvaConfig
from ava.model import build_model, set_router_bias
from ava.tokenizer import AvaTokenizer
from model_1b import AvaModel1B, apply_rope_scaling

_REPO = Path(__file__).resolve().parent.parent
EVAL_SEED = 1234


def _tokenizer_path(cfg: AvaConfig) -> Path:
    raw = cfg.data.get("tokenizer_path", "data/nano/tokenizer/ava_nano_bpe.json")
    p = Path(raw)
    if not p.is_absolute():
        p = _REPO / p
    return p


def load_model(
    ckpt_path: str | None,
    preset: str,
    device: str | torch.device = "cpu",
    *,
    use_memory: bool = False,
    branch_chat: bool = False,
) -> tuple[AvaModel1B, AvaTokenizer, str]:
    """Build model, optionally load checkpoint, return (model, tokenizer, ckpt_label)."""
    cfg = AvaConfig.load(preset)
    model = build_model(cfg, use_memory=use_memory)
    dev = torch.device(device)

    tok_path = _tokenizer_path(cfg)
    if not tok_path.exists():
        raise FileNotFoundError(
            f"tokenizer missing at {tok_path}. Run scripts/build_eval_data.py first."
        )
    tokenizer = AvaTokenizer.load(tok_path)

    label = "random-init"
    if ckpt_path and ckpt_path != "none":
        blob = torch.load(ckpt_path, map_location=dev, weights_only=False)
        model.load_state_dict(blob["model"])
        label = str(ckpt_path)
        if branch_chat and cfg.branch_chat:
            spec = cfg.branch_chat
            model.freeze_spaces(list(spec.get("freeze", [])))
            bias = spec.get("router_bias")
            if bias is not None:
                set_router_bias(model, list(bias))

    model.eval().to(dev)
    return model, tokenizer, label


def prep_eval(model: AvaModel1B, seed: int = EVAL_SEED) -> None:
    """Standard eval preamble: fixed seed + cleared workspace memory."""
    torch.manual_seed(seed)
    model.reset_memory()


def greedy_decode(
    model: AvaModel1B,
    prompt_ids: list[int],
    *,
    max_new: int = 8,
    task_type: str = "deliberate",
    device: torch.device | None = None,
) -> list[int]:
    """Argmax autoregressive decode (no KV cache — fine at nano scale)."""
    dev = device or next(model.parameters()).device
    ids = list(prompt_ids)
    for _ in range(max_new):
        x = torch.tensor([ids], dtype=torch.long, device=dev)
        with torch.no_grad():
            out = model(input_ids=x, task_type=task_type)
        nxt = int(out["lm_logits"][0, -1].argmax().item())
        ids.append(nxt)
    return ids


def logprob_of(
    model: AvaModel1B,
    prompt_ids: list[int],
    target: str,
    tokenizer: AvaTokenizer,
    *,
    task_type: str = "deliberate",
    device: torch.device | None = None,
) -> float:
    """Sum log-softmax of target token(s) at the positions immediately after prompt."""
    dev = device or next(model.parameters()).device
    target_ids = tokenizer.encode(target)
    if not target_ids:
        raise ValueError(f"target {target!r} encodes to nothing")

    full = prompt_ids + target_ids
    x = torch.tensor([full], dtype=torch.long, device=dev)
    with torch.no_grad():
        logits = model(input_ids=x, task_type=task_type)["lm_logits"][0]

    start = len(prompt_ids)
    total = 0.0
    for i, tid in enumerate(target_ids):
        pos = start + i - 1
        if pos < 0:
            continue
        lp = F.log_softmax(logits[pos].float(), dim=-1)
        total += float(lp[tid].item())
    return total


def forward_out(
    model: AvaModel1B,
    prompt_ids: list[int],
    *,
    task_type: str = "deliberate",
    device: torch.device | None = None,
) -> dict[str, Any]:
    dev = device or next(model.parameters()).device
    x = torch.tensor([prompt_ids], dtype=torch.long, device=dev)
    with torch.no_grad():
        return model(input_ids=x, task_type=task_type)


def count_state_tensors(model: AvaModel1B, ckpt_path: str | None) -> int:
    """Assert checkpoint tensor count matches built model when loading."""
    if not ckpt_path or ckpt_path == "none":
        return sum(1 for _ in model.state_dict())
    blob = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    ck = blob["model"]
    built = model.state_dict()
    if set(ck.keys()) != set(built.keys()):
        missing = set(built) - set(ck)
        extra = set(ck) - set(built)
        raise ValueError(f"checkpoint key mismatch: missing={sorted(missing)[:5]} extra={sorted(extra)[:5]}")
    return len(ck)


def data_dir(preset: str) -> Path:
    cfg = AvaConfig.load(preset)
    raw = cfg.data.get("packed_dir", f"data/{preset}")
    p = Path(raw)
    if not p.is_absolute():
        p = _REPO / p.parent  # data/nano from packed_dir data/nano/packed
    return _REPO / "data" / preset


def heldout_path(preset: str, phase: int) -> Path:
    return data_dir(preset) / f"heldout_phase{phase}.bin"
