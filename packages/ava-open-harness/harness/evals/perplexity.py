"""
perplexity.py — per-phase perplexity eval (one eval per file; probes/needle live in their own files)

Mock mode: seed-varying deterministic mock.
Real mode: delegates to factory evals/perplexity.compute_ppl over the heldout
bins. If no heldout bin exists (the cpu_pilot smoke run ships packed training
shards but no heldout split), it computes a REAL windowed NLL over the pilot's
packed shards instead — explicitly labeled heldout=False / training
distribution, so the number is honest about what it measures.

Solo personal project, no connection to employer, built with public/free-tier only
"""

from __future__ import annotations

import glob
import math
import os
import random
from typing import Any

from ..common import (
    MockModel,
    _extract_logits,
    attach_smoke_labels,
    factory_modules,
    factory_root,
    real_unimplemented,
)
from ..registry import register_eval

BAR = "avg<30"


def _ppl_over_packed(
    model: Any, device: str, max_windows: int, seq_len: int
) -> dict[str, Any] | None:
    """Real windowed PPL over the cpu_pilot packed shards (training distribution).

    Returns a measured dict, or None if no packed shard exists. Every number is
    computed from live forward passes; the measurement is explicitly labeled as
    NOT heldout."""
    import numpy as np
    import torch
    import torch.nn.functional as F

    packed = sorted(
        glob.glob(os.path.join(factory_root(), "runs", "cpu_pilot", "packed", "*.bin"))
    )
    if not packed:
        return None
    path = packed[0]
    arr = np.memmap(path, dtype=np.uint16, mode="r")
    if arr.size < seq_len + 1:
        return None
    dev = torch.device(device)
    nll_sum = 0.0
    n_preds = 0
    n_windows = 0
    model.eval()
    with torch.no_grad():
        for start in range(0, arr.size - seq_len, seq_len):
            if n_windows >= max_windows:
                break
            window = arr[start : start + seq_len + 1].astype(np.int64)
            x = torch.tensor(window[:-1], device=dev).unsqueeze(0)
            y = torch.tensor(window[1:], device=dev)
            logits = _extract_logits(model(input_ids=x), torch)[0]
            lp = F.log_softmax(logits.float(), dim=-1)
            nll = -lp[torch.arange(seq_len, device=dev), y]
            nll_sum += float(nll.sum().item())
            n_preds += seq_len
            n_windows += 1
    if n_preds == 0:
        return None
    avg_ppl = float(math.exp(nll_sum / n_preds))
    return {
        "avg_ppl": avg_ppl,
        "tokens": n_preds,
        "windows": n_windows,
        "seq_len": seq_len,
        "source": path,
        "heldout": False,
        "note": (
            "no heldout bins found; PPL measured on cpu_pilot packed shards "
            "(training distribution) — a real measurement, but NOT a heldout PPL"
        ),
    }


@register_eval(
    name="perplexity", description="Per-phase PPL on heldout bins", group="core"
)
def perplexity(
    model: Any,
    tokenizer: Any,
    device: str = "cpu",
    phases: list[int] | None = None,
    **kw,
) -> dict[str, Any]:
    phases = phases or list(range(6))
    if not isinstance(model, MockModel):
        mods, err = factory_modules()
        if mods is None:
            return real_unimplemented(
                "perplexity",
                BAR,
                f"factory evals not importable from {factory_root()} ({err})",
            )
        preset = kw.get("preset", "nano")
        per_phase = mods["evals.perplexity"].compute_ppl(
            model, preset, phases, device=device
        )
        finite = {
            ph: v
            for ph, v in per_phase.items()
            if isinstance(v.get("ppl"), float) and math.isfinite(v["ppl"])
        }
        if finite:
            avg = sum(v["ppl"] for v in finite.values()) / len(finite)
            measured = {
                "per_phase": {f"phase_{ph}": v for ph, v in per_phase.items()},
                "avg_ppl": avg,
                "source": "factory heldout bins",
                "heldout": True,
            }
            return attach_smoke_labels(
                {
                    "test": "perplexity",
                    "measured": measured,
                    "pass": avg < 30,
                    "bar": BAR,
                }
            )
        # heldout bins missing → real measurement over pilot packed shards
        measured = _ppl_over_packed(
            model,
            device,
            max_windows=int(kw.get("ppl_max_windows", 40)),
            seq_len=int(kw.get("ppl_seq_len", 256)),
        )
        if measured is None:
            return real_unimplemented(
                "perplexity",
                BAR,
                "no heldout bins and no cpu_pilot packed shards found under "
                f"{factory_root()}; regenerate via factory scripts/cpu_pilot_e2e.py",
            )
        measured["heldout_errors"] = {
            f"phase_{ph}": v.get("error", "") for ph, v in per_phase.items()
        }
        return attach_smoke_labels(
            {
                "test": "perplexity",
                "measured": measured,
                "pass": measured["avg_ppl"] < 30,
                "bar": BAR,
            }
        )
    results = {}
    for ph in phases:
        random.seed(model.seed + ph)
        ppl = random.uniform(12.0, 35.0) - ph * 1.5  # decreasing with phase
        results[f"phase_{ph}"] = {"ppl": ppl, "tokens": 200000}
    avg = sum(v["ppl"] for v in results.values()) / len(results)
    return {
        "test": "perplexity",
        "measured": {"per_phase": results, "avg_ppl": avg},
        "pass": avg < 30,
        "bar": BAR,
    }
