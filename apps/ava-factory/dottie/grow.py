# Solo personal project, no connection to employer, built with public/free-tier only
"""Function-preserving model growth: warm-start a bigger preset from a smaller one.

`python -m dottie.grow --src /ckpt/base_final.pt --src-preset mini --dst-preset base1b \\
    --out /ckpt/base1b/grown_init.pt --validate`

writes a checkpoint whose `model` state dict has the DESTINATION preset's geometry but is
initialised from the source checkpoint's weights, so base1b starts from what mini learned
instead of from random init (Net2Net / bert2BERT family). Train from it with
`python -m dottie.train --preset base1b --init /ckpt/base1b/grown_init.pt`.

The mechanism is **zero-pad grafting**, chosen over weight tiling because every preset
ties its lm_head to the embedding — tiling inflates tied-head logits by the width ratio
and, with no final norm before the head in this architecture, there is nowhere to hide
the compensation. Grafting has none of that: the source weights occupy the leading slice
of every tensor, new OUTPUT rows are zeroed (new capacity writes nothing at init, so the
big model computes exactly the small model's function), and new INPUT columns keep their
fresh init (so gradients wake the new capacity: zeroed write-rows see nonzero gradients
from step one, populate the new stream dims, and the kept columns follow). RMSNorm gains
on a grown dim are rescaled by sqrt(d_src/d_dst) — the norm averages over zeros it now
sees — which restores the source activations exactly.

Honesty contract — what is and is not preserved:

- **Exact** when vocab, head_dim, and layer counts match and only widths grow (any
  ratio — 768→2048 included). The unit tests assert logit equality for that case.
- Depth stretching (layer j reads source layer floor(j*n_src/n_dst)) and head_dim
  changes (mini 64 → base1b 128, MHA→GQA) are APPROXIMATE: same grafting rules, head
  alignment preserved where shapes allow, nothing fabricated. Whether the warm start is
  worth anything is MEASURED, not assumed: `--validate` runs source, grown, and a
  random-init destination model on one fixed batch and reports all three losses. The
  grown model earning a lower initial loss than fresh init is the whole claim.
- Tensors that exist only in the destination keep their fresh init and are listed in the
  manifest as `dst_only`. A vocab mismatch is a hard refusal (different tokenizer = the
  embeddings mean nothing to each other) unless `--allow-partial` explicitly keeps fresh
  embeddings.

Every grown checkpoint carries a `grow` manifest (per-tensor disposition + validation
numbers) so a later reader can see how it was made — no silent provenance.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from pathlib import Path
from typing import Any

import torch
from model_1b import RMSNorm
from torch import nn

from dottie.config import DottieConfig
from dottie.model import build_model, count_params

# Layer lists that may change depth between presets; dst layer j reads src layer
# floor(j * n_src / n_dst) (stretch mapping — standard progressive-stacking practice).
LAYER_LISTS = ("text_layers", "fusion_layers", "reasoning_layers")

_LAYER_KEY = re.compile(r"^(" + "|".join(LAYER_LISTS) + r")\.(\d+)\.(.+)$")


# ---------------------------------------------------------------------------
# grafting primitives
# ---------------------------------------------------------------------------


def _leading(dst_shape: tuple[int, ...], src: torch.Tensor) -> tuple[slice, ...]:
    return tuple(slice(0, s) for s in src.shape)


def _graft_linear_weight(src: torch.Tensor, dst_init: torch.Tensor) -> torch.Tensor:
    """[out, in]: src in the leading block; NEW OUTPUT ROWS ZERO (write nothing at
    init — this is what makes growth exact); new input columns keep fresh init (they
    read zero stream dims at init and are the wake-up path for the new capacity)."""
    g = dst_init.clone()
    out_s, in_s = src.shape
    g[out_s:, :] = 0.0
    g[:out_s, :in_s] = src
    return g


def _graft_zero_rest(src: torch.Tensor, dst_init: torch.Tensor) -> torch.Tensor:
    """src in the leading slice, everything else zero (embeddings, biases: they write
    the stream, so new dims must contribute nothing at init)."""
    g = torch.zeros_like(dst_init)
    g[_leading(dst_init.shape, src)] = src
    return g


def _graft_keep_rest(src: torch.Tensor, dst_init: torch.Tensor) -> torch.Tensor:
    """src in the leading slice, fresh init elsewhere — for tensors whose extra
    entries are inert at init (per-head params of dead heads, exotic buffers)."""
    g = dst_init.clone()
    g[_leading(dst_init.shape, src)] = src
    return g


def _graft_qkv_sections(src: torch.Tensor, dst_init: torch.Tensor) -> torch.Tensor:
    """nn.MultiheadAttention packs q/k/v as three equal sections along dim 0; graft
    each section with the Linear rule (weights) or zero-rest (bias)."""
    s3, d3 = src.shape[0] // 3, dst_init.shape[0] // 3
    g = dst_init.clone()
    for i in range(3):
        s_sec, d_sec = src[i * s3 : (i + 1) * s3], dst_init[i * d3 : (i + 1) * d3]
        g[i * d3 : (i + 1) * d3] = (
            _graft_linear_weight(s_sec, d_sec)
            if src.ndim == 2
            else _graft_zero_rest(s_sec, d_sec)
        )
    return g


def _graft_norm_gain(src: torch.Tensor, dst_init: torch.Tensor) -> torch.Tensor:
    """RMSNorm over a zero-padded stream divides by rms computed across the zeros,
    inflating the live dims by sqrt(d_dst/d_src); the leading gains absorb it."""
    g = dst_init.clone()
    d_s, d_d = src.shape[0], dst_init.shape[0]
    g[:d_s] = src * math.sqrt(d_s / d_d)
    return g


# ---------------------------------------------------------------------------
# growth
# ---------------------------------------------------------------------------


def _param_owner_map(model: nn.Module) -> dict[str, nn.Module]:
    """state-dict key -> owning module, so grafting rules dispatch on module type."""
    owners: dict[str, nn.Module] = {}
    for mod_name, mod in model.named_modules():
        prefix = mod_name + "." if mod_name else ""
        for p_name, _ in list(mod.named_parameters(recurse=False)) + list(
            mod.named_buffers(recurse=False)
        ):
            owners[prefix + p_name] = mod
    return owners


def _depth_maps(src_sd: dict, dst_sd: dict) -> dict[str, dict[int, int]]:
    maps: dict[str, dict[int, int]] = {}
    for lst in LAYER_LISTS:
        src_idx = {
            int(m.group(2))
            for k in src_sd
            if (m := _LAYER_KEY.match(k)) and m.group(1) == lst
        }
        dst_idx = {
            int(m.group(2))
            for k in dst_sd
            if (m := _LAYER_KEY.match(k)) and m.group(1) == lst
        }
        if src_idx and dst_idx and len(src_idx) != len(dst_idx):
            ns, nd = len(src_idx), len(dst_idx)
            maps[lst] = {j: (j * ns) // nd for j in range(nd)}
    return maps


def _src_key_for(dst_key: str, depth_maps: dict[str, dict[int, int]]) -> str:
    m = _LAYER_KEY.match(dst_key)
    if not m:
        return dst_key
    lst, j, rest = m.group(1), int(m.group(2)), m.group(3)
    mapping = depth_maps.get(lst)
    if mapping is None or j not in mapping:
        return dst_key
    return f"{lst}.{mapping[j]}.{rest}"


def grow_state_dict(
    src_sd: dict[str, torch.Tensor],
    dst_model: nn.Module,
    *,
    src_cfg: DottieConfig,
    dst_cfg: DottieConfig,
    allow_partial: bool = False,
) -> tuple[dict[str, torch.Tensor], dict]:
    """Return (grown state dict for dst_model, manifest). Raises on vocab mismatch
    unless allow_partial (fresh embeddings are almost never what you want)."""
    if (src_cfg.model.vocab_size != dst_cfg.model.vocab_size) and not allow_partial:
        raise SystemExit(
            f"vocab mismatch: src {src_cfg.model.vocab_size} vs dst "
            f"{dst_cfg.model.vocab_size} — different tokenizers make the embeddings "
            "meaningless to each other. Pass --allow-partial to keep fresh embeddings "
            "(and expect a much weaker warm start)."
        )

    dst_sd = dst_model.state_dict()
    depth = _depth_maps(src_sd, dst_sd)
    owners = _param_owner_map(dst_model)
    grown: dict[str, torch.Tensor] = {}
    manifest: dict[str, list[str]] = {
        "copied": [],
        "grafted_exact": [],
        "grafted": [],
        "dst_only": [],
        "vocab_fresh": [],
    }

    for key, dst_t in dst_sd.items():
        src_key = _src_key_for(key, depth)
        src_t = src_sd.get(src_key)
        if src_t is None:
            manifest["dst_only"].append(key)
            grown[key] = dst_t
            continue
        if src_cfg.model.vocab_size != dst_cfg.model.vocab_size and any(
            s == src_cfg.model.vocab_size for s in src_t.shape
        ):
            manifest["vocab_fresh"].append(key)
            grown[key] = dst_t
            continue
        src_t = src_t.to(dst_t.dtype)
        if tuple(src_t.shape) == tuple(dst_t.shape):
            grown[key] = src_t.clone()
            manifest["copied"].append(key)
            continue
        if src_t.ndim != dst_t.ndim or any(
            s > d for s, d in zip(src_t.shape, dst_t.shape, strict=False)
        ):
            manifest["dst_only"].append(key)  # shrink/rank change: no sane graft
            grown[key] = dst_t
            continue
        owner = owners.get(key)
        if isinstance(owner, nn.MultiheadAttention) and "in_proj_" in key:
            # Packed q/k/v: three stacked sections along dim 0. The plain leading-slice
            # graft would misalign k and v into q's section (observed: 5e-2 divergence
            # through every workspace read); graft each section independently.
            grown[key] = _graft_qkv_sections(src_t, dst_t)
            manifest["grafted_exact"].append(key)
        elif (
            isinstance(owner, nn.Linear) and key.endswith("weight") and src_t.ndim == 2
        ):
            grown[key] = _graft_linear_weight(src_t, dst_t)
            manifest["grafted_exact"].append(key)
        elif isinstance(owner, nn.Embedding) and key.endswith("weight"):
            grown[key] = _graft_zero_rest(src_t, dst_t)  # new stream dims write nothing
            manifest["grafted_exact"].append(key)
        elif isinstance(owner, RMSNorm) and src_t.ndim == 1:
            grown[key] = _graft_norm_gain(src_t, dst_t)
            manifest["grafted_exact"].append(key)
        elif key.endswith("bias") and src_t.ndim == 1:
            grown[key] = _graft_zero_rest(src_t, dst_t)
            manifest["grafted_exact"].append(key)
        else:
            # Conservative fallback: new entries contribute NOTHING at init (zero), so
            # unclassified tensors (slot embeddings, per-head params, buffers) cannot
            # leak fresh-init noise into the preserved function. They wake via the
            # nonzero gradients flowing from the kept input columns.
            grown[key] = _graft_zero_rest(src_t, dst_t)
            manifest["grafted"].append(key)

    _enforce_tied_consistency(dst_model, grown, manifest)
    return grown, manifest


def _enforce_tied_consistency(
    dst_model: nn.Module, grown: dict[str, torch.Tensor], manifest: dict[str, list[str]]
) -> None:
    """Keys sharing ONE storage (tie_lm_head, tie_verbalizer) must get ONE grafted
    value — otherwise whichever key loads last silently overwrites the others (observed:
    verbalizer's keep-rest graft clobbered the embedding's zero-rest graft through the
    shared tensor, polluting every new stream dim). The zero-rest embedding graft is the
    strictest rule in any tie group, so it wins."""
    groups: dict[int, list[str]] = {}
    for name, p in dst_model.named_parameters(remove_duplicate=False):
        groups.setdefault(p.data_ptr(), []).append(name)
    for keys in groups.values():
        keys = [k for k in keys if k in grown]
        if len(keys) < 2:
            continue
        embed_owned = [k for k in keys if k.endswith("embed.weight") or ".embed." in k]
        winner = embed_owned[0] if embed_owned else keys[0]
        for k in keys:
            if k != winner and not torch.equal(grown[k], grown[winner]):
                grown[k] = grown[winner]
                manifest.setdefault("tied_to", []).append(f"{k} <- {winner}")


# ---------------------------------------------------------------------------
# validation — measured, never assumed
# ---------------------------------------------------------------------------


@torch.no_grad()
def _lm_loss(model: nn.Module, ids: torch.Tensor) -> float:
    model.eval()
    out = model(input_ids=ids, task_type="automatic")
    logits = out["lm_logits"][:, :-1, :]
    targets = ids[:, 1:]
    return float(
        nn.functional.cross_entropy(
            logits.reshape(-1, logits.shape[-1]).float(), targets.reshape(-1)
        )
    )


def validate_growth(
    src_model: nn.Module,
    grown_model: nn.Module,
    fresh_model: nn.Module,
    *,
    vocab: int,
    seq: int = 128,
    batch: int = 4,
    seed: int = 1234,
) -> dict:
    """One fixed batch through source, grown, and random-init destination. The grown
    model beating fresh init is the warm-start claim; src == grown means exact
    preservation. Random tokens are fine here: preservation is a property of the
    function, not the data distribution."""
    g = torch.Generator().manual_seed(seed)
    ids = torch.randint(0, vocab, (batch, seq), generator=g)
    return {
        "src_loss": round(_lm_loss(src_model, ids), 5),
        "grown_loss": round(_lm_loss(grown_model, ids), 5),
        "fresh_dst_loss": round(_lm_loss(fresh_model, ids), 5),
        "batch": [batch, seq],
        "seed": seed,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="dottie.grow", description=__doc__.split("\n")[0])
    ap.add_argument("--src", required=True, help="source checkpoint (.pt)")
    ap.add_argument("--src-preset", required=True)
    ap.add_argument("--dst-preset", required=True)
    ap.add_argument("--out", required=True, help="output checkpoint path")
    ap.add_argument(
        "--validate",
        action="store_true",
        help="run src/grown/fresh on one fixed batch and report losses",
    )
    ap.add_argument(
        "--allow-partial",
        action="store_true",
        help="permit vocab mismatch (fresh embeddings) — weak warm start",
    )
    args = ap.parse_args(argv)

    src_cfg = DottieConfig.load(args.src_preset)
    dst_cfg = DottieConfig.load(args.dst_preset)
    blob = torch.load(args.src, map_location="cpu", weights_only=False)
    src_sd = blob["model"]

    src_model = build_model(src_cfg)
    src_model.load_state_dict(src_sd)
    dst_model = build_model(dst_cfg)

    grown, manifest = grow_state_dict(
        src_sd,
        dst_model,
        src_cfg=src_cfg,
        dst_cfg=dst_cfg,
        allow_partial=args.allow_partial,
    )
    counts = {k: len(v) for k, v in manifest.items()}
    report: dict[str, Any] = {
        "src": args.src,
        "src_preset": args.src_preset,
        "dst_preset": args.dst_preset,
        "src_params": count_params(src_model),
        "dst_params": count_params(dst_model),
        "src_step": blob.get("step"),
        "tensors": counts,
    }

    dst_model.load_state_dict(grown)
    if args.validate:
        fresh = build_model(dst_cfg)
        report["validation"] = validate_growth(
            src_model,
            dst_model,
            fresh,
            vocab=min(src_cfg.model.vocab_size, dst_cfg.model.vocab_size),
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model": grown,
            "step": 0,
            "phase": 0,
            "tokens_done": 0,
            "preset": args.dst_preset,
            "grow": {**report, "ts": time.time(), "manifest": manifest},
        },
        out,
    )
    out.with_suffix(".grow.json").write_text(
        json.dumps({**report, "manifest": manifest}, indent=2), encoding="utf-8"
    )
    print(json.dumps({"ok": True, "out": str(out), **report}, indent=2))
    if args.validate:
        v = report["validation"]
        if v["grown_loss"] >= v["fresh_dst_loss"]:
            print(
                json.dumps(
                    {
                        "warning": "grown init is NOT better than fresh init on the "
                        "probe batch — the warm start bought nothing"
                    }
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
