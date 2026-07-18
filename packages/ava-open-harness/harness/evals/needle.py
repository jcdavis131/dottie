"""
needle.py — pass-key retrieval eval (one eval per file; perplexity/probes live in their own files)

Mock mode: seed-varying deterministic mock.
Real mode: delegates to factory evals/needle.run_needle (native + YaRN-scaled
contexts, live greedy decodes).

Solo personal project, no connection to employer, built with public/free-tier only
"""
from __future__ import annotations
from typing import Any, Dict
from ..registry import register_eval
from ..common import (
    MockModel, real_unimplemented, factory_modules, factory_root, attach_smoke_labels,
)
import random

BAR = "avg>=0.70"

@register_eval(name="needle", description="Pass-key retrieval depth 0.1..0.9 with YaRN scaling", group="core")
def needle(model: Any, tokenizer: Any, device: str="cpu", **kw) -> Dict[str,Any]:
    if not isinstance(model, MockModel):
        mods, err = factory_modules()
        if mods is None:
            return real_unimplemented(
                "needle", BAR,
                f"factory evals not importable from {factory_root()} ({err})",
            )
        res = mods["evals.needle"].run_needle(
            model, tokenizer,
            samples_per_depth=int(kw.get("needle_samples_per_depth", 10)),
            device=device,
        )
        accs = [a for ctx in ("native", "yarn") for a in res.get(ctx, {}).values()]
        avg = sum(accs) / len(accs) if accs else 0.0
        measured = {"native": res.get("native", {}), "yarn": res.get("yarn", {}), "avg": avg}
        return attach_smoke_labels(
            {"test": "needle", "measured": measured, "pass": avg >= 0.70, "bar": BAR})
    depths = [0.1,0.3,0.5,0.7,0.9]
    results = {}
    for d in depths:
        random.seed(model.seed + int(d*10))
        acc = random.uniform(0.7, 0.95) if d<0.6 else random.uniform(0.5,0.8)
        results[str(d)] = acc
    avg = sum(results.values())/len(results)
    return {"test":"needle", "measured": {"per_depth": results, "avg": avg, "contexts":[1024,2048]}, "pass": avg>=0.70, "bar":BAR}
