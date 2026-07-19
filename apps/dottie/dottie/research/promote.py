# Solo personal project, no connection to employer, built with public/free-tier only
"""SOTA promotion bundles — the human-gated bridge from the research loop to the factory.

When an experiment reaches ``sota`` the loop has PROVEN (real training, real held-out
measurement) that its module beats the baseline at nano scale. This module turns that
proof into a reviewable promotion bundle under ``<data_dir>/research/promotions/<id>/``:

    candidate.py        the exact validated module that earned the metric
    PROMOTION.md        the evidence: hypothesis, measured metrics vs baseline, provenance
    ab_nano.py          a runnable A/B script (candidate vs unmodified) for re-verification

NOTHING is auto-applied to the factory model. A human reads PROMOTION.md, reruns
ab_nano.py if they wish, and only then wires the block into model_1b presets. The
bundle generator refuses honestly when the experiment is not sota or its workspace
module is missing — a promotion without its exact artifact would be provenance theater.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from dottie.research.ledger import SOTA, Ledger

_AB_TEMPLATE = '''# Auto-generated A/B re-verification for research promotion {exp_id}.
# Runs the SAME factory nano recipe on the unmodified model and on the candidate,
# printing both held-out losses. Requires torch + AVA_FACTORY_ROOT + packed corpus.
from dottie.research.factory_trainer import run_baseline_calibration, factory_nano_trainer

STEPS = {steps}

baseline = run_baseline_calibration({{"steps": STEPS}})
print("unmodified:", baseline)
candidate = factory_nano_trainer(r"{module_path}", {{"steps": STEPS}})
print("candidate: ", candidate)
'''


def build_promotion(ledger: Ledger, exp_id: str, *, out_root: str | Path,
                    ts: Optional[float] = None) -> Dict[str, Any]:
    """Write the bundle for a sota experiment. Raises ValueError on a non-sota
    experiment or a missing workspace module (honest refusals, not empty bundles)."""
    exp = ledger.get(exp_id)
    if exp is None:
        raise ValueError(f"unknown experiment {exp_id!r}")
    if exp.state != SOTA:
        raise ValueError(f"experiment {exp_id} is {exp.state!r}, not sota — only proven "
                         "winners get promotion bundles")
    impl = exp.implementation or {}
    code = impl.get("code")
    if not code:
        raise ValueError(f"experiment {exp_id} has no recorded implementation code")

    b = ledger.get_baseline()
    metrics = exp.train_metrics or {}
    steps = int((metrics.get("config") or {}).get("steps", 150)) if isinstance(
        metrics.get("config"), dict) else 150

    out = Path(out_root) / exp_id
    out.mkdir(parents=True, exist_ok=True)
    module_path = out / "candidate.py"
    module_path.write_text(code, encoding="utf-8")

    hyp = exp.hypothesis or {}
    md = [
        f"# Research promotion — {hyp.get('hypothesis_name', exp_id)}",
        "",
        f"- experiment: `{exp_id}`  |  state: **sota**  |  generated: "
        f"{time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime(ts or time.time()))}",
        f"- metric: `{b.metric_name}` — candidate **{metrics.get(b.metric_name)}** vs "
        f"baseline-at-evaluation (see eval_verdict below); lower is "
        f"{'worse' if b.higher_is_better else 'better'}",
        "",
        "## Hypothesis",
        str(hyp.get("theoretical_intuition", "(none recorded)")),
        "",
        "## Measured",
        "```json", json.dumps(metrics, indent=2, default=str), "```",
        "## Verdict",
        "```json", json.dumps(exp.eval_verdict or {}, indent=2, default=str), "```",
        "",
        "## Next steps (HUMAN-GATED — nothing here is auto-applied)",
        f"1. Re-verify: `python {out.name}/ab_nano.py` (factory checkout + packed corpus).",
        "2. If it reproduces, wire the block into the target preset the same way",
        "   `deltanet_layers` swaps a fusion block, behind a config gate.",
        "3. Gate the preset change through the eval harness before ANY promotion to serve.",
    ]
    (out / "PROMOTION.md").write_text("\n".join(md), encoding="utf-8")
    (out / "ab_nano.py").write_text(
        _AB_TEMPLATE.format(exp_id=exp_id, steps=steps,
                            module_path=str(module_path.resolve())),
        encoding="utf-8")
    return {"experiment": exp_id, "bundle": str(out),
            "files": ["candidate.py", "PROMOTION.md", "ab_nano.py"]}


def build_pending_promotions(ledger: Ledger, *, out_root: str | Path) -> Dict[str, Any]:
    """Bundle every sota experiment that has no bundle yet. Returns a summary."""
    out_root = Path(out_root)
    built, skipped = [], []
    for exp in ledger.list(state=SOTA):
        if (out_root / exp.id / "PROMOTION.md").exists():
            skipped.append(exp.id)
            continue
        try:
            built.append(build_promotion(ledger, exp.id, out_root=out_root))
        except ValueError as e:
            skipped.append(f"{exp.id}: {e}")
    return {"built": built, "already_bundled": skipped}
