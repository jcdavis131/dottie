# Solo personal project, no connection to employer, built with public/free-tier only
"""Pre-registered analysis of the loop's behaviour AFTER the 2026-07-20 08:50:02 restart.

    apps/dottie> .venv/Scripts/python.exe scripts/post_restart_report.py

Written BEFORE the data existed, on purpose. The gates measured here are ones I built the
same night, and TODOS §5.3.R21 records the obvious hazard: I have a stake in these numbers
moving. Fixing the questions, the population, and the reporting threshold in advance is the
cheapest defence against choosing a favourable cut afterwards.

WHAT IS FIXED HERE, AND WHY

* **Population** — experiments with `updated_ts >= BOOT_TS`. Scoped by the daemon's own
  `boot` record, never by commit timestamps: the daemon does not live-reload, so commit time
  is the wrong boundary and silently mislabels experiments that ran on older code
  (§5.3.R8 lost a whole comparison to exactly this).
* **Threshold** — no rate is printed below MIN_N genuine outcomes. It prints
  "INSUFFICIENT n" and the current count instead. The constraint-8 attempt died at n=5 and
  the honest answer was "not measurable"; this makes that answer the default rather than a
  judgement call made while looking at the numbers.
* **Pre-restart comparators** are hardcoded below from §5.3.R12/R17/R18, measured before
  any of this shipped. They are not recomputed here, so they cannot drift to flatter a
  result.

None of these questions is "did my gates help?" — that is not directly measurable from this
data. They ask what the loop now PRODUCES. A gate can be working perfectly and the rates can
stay flat, if the model simply keeps proposing the same things and the gates keep rejecting
them; that would show up as a higher rejection rate with an unchanged proposal mix, which is
a different (and still useful) result.
"""
from __future__ import annotations

import collections
import datetime
import importlib.util
import json
import os
import re
import sqlite3
import tempfile
import uuid
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

warnings.filterwarnings("ignore")

BOOT_TS = datetime.datetime(2026, 7, 20, 10, 35, 2).timestamp()
MIN_N = 20
LEDGER = Path(__file__).resolve().parents[1] / "data" / "research" / "ledger.sqlite3"

# Measured pre-restart (§5.3.R12, R17, R18). Hardcoded so they cannot drift.
PRE = {
    "category_error_rate": (30, 84, "36%"),      # of all proposals
    "zero_param_rate": (11, 20, "55%"),          # of candidates that passed validation
    "block_shaped_with_capacity": (5, 84, "6%"),  # of all proposals
    # 46/59, the WHOLE pre-restart population. §5.3.R8 quotes 74% (35/47) but that was the
    # pre-constraint-8 sub-bucket, not everything before the restart. Comparing post-restart
    # against a sub-bucket would have invented a 4-point improvement out of a boundary
    # mismatch — caught by running this report over the pre-restart data, where the
    # recomputed figure came back 78% and did not match the constant.
    "dry_run_share": (46, 59, "78%"),            # of genuine validation failures
}
#: What the daemon was ACTUALLY running during the measured window, keyed to the git_sha in
#: its own `boot` record. The daemon does not live-reload, so commits made after it started
#: are NOT in this data — and the honest attribution depends entirely on which is which.
#: Written 2026-07-20 while n was still 4, deliberately: once numbers exist, the temptation
#: is to credit whichever fix looks best. §5.3.R8 lost an entire comparison to this.
BOOT_SHA = "c12a052"
LIVE_IN_WINDOW = [
    "§5.3.R12 ideation reframing (block-shaped answers to loss-shaped bottlenecks)",
    "§5.3.R17 zero-parameter gate (correctable failure)",
    "§5.3.R19 learnable_parameters field in the ideation schema",
    "§5.3.R8/R10/R11 integration-width, residual-stream and rank-collapse stages",
    "§5.3.R24 dead-ends anti-priming (round-robin + overused-terms tally)",
    "§5.3.R28 integration SEQUENCE probe (seq=256, not just hidden)",
    "§5.3.R29 forward-time sequence-length guidance in the implementation prompt",
    "§5.3.R35 SEARCH SPACE no longer asks for losses/regularisers  <- the big one",
    "§5.3.R36/R37 the other two prompt contradictions (rigor section, codebase context)",
    "§5.3.R38 the corrector now carries the engineering constraints  <- the other big one",
    "§5.3.R42 contract check no longer vanishes when unscoped",
    "§5.3.R45 factory_trainer load failure -> failed_training, not retryable",
]
NOT_IN_WINDOW = [
    "§5.3.R46 proxy-trainer training-loop guard (train.py; the daemon uses --trainer factory,"
    " so this affects the proxy path only)",
]

CATEGORY = re.compile(r"regulari[sz]|loss|penalt|objective|schedul|curricul", re.I)
DIM_KWARGS = ("d_model", "dim", "hidden", "hidden_dim", "hidden_size", "embed_dim",
              "input_dim", "n_embd", "channels", "width")


def n_params_of(impl: Dict[str, Any]) -> Optional[int]:
    """Learnable parameter count, or None if the module cannot be instantiated now."""
    code, dry = impl.get("code"), impl.get("dry_run") or {}
    if not code:
        return None
    d = tempfile.mkdtemp()
    f = os.path.join(d, "c.py")
    Path(f).write_text(code, encoding="utf-8")
    try:
        spec = importlib.util.spec_from_file_location("m" + uuid.uuid4().hex[:8], f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cls = getattr(mod, dry.get("class_name") or "", None)
        if cls is None:
            return None
        kw = dict(dry.get("init_kwargs") or {})
        for k in DIM_KWARGS:
            if k in kw:
                kw[k] = 64
        return sum(p.numel() for p in cls(**kw).parameters() if p.requires_grad)
    except Exception:
        return None


def rate(label: str, num: int, den: int, pre_key: str) -> None:
    pre_num, pre_den, pre_str = PRE[pre_key]
    if den < MIN_N:
        print(f"  {label:34s} INSUFFICIENT n ({den} of {MIN_N} needed)   "
              f"[pre-restart {pre_str}]")
        return
    pct = 100.0 * num / den
    delta = pct - (100.0 * pre_num / pre_den)
    arrow = "down" if delta < 0 else ("up" if delta > 0 else "flat")
    print(f"  {label:34s} {num}/{den} = {pct:.0f}%   "
          f"[pre-restart {pre_str}]  {arrow} {abs(delta):.0f} pts")


def main() -> int:
    c = sqlite3.connect(LEDGER)
    c.row_factory = sqlite3.Row
    rows = list(c.execute("select id,state,created_ts,updated_ts,failure,hypothesis,"
                          "implementation from experiments where updated_ts >= ?", (BOOT_TS,)))
    print(f"post-restart population: {len(rows)} experiments touched since "
          f"{datetime.datetime.fromtimestamp(BOOT_TS):%H:%M:%S}")
    print(f"reporting threshold: n >= {MIN_N} (below that, rates are withheld)")
    print(f"\nWHAT THIS WINDOW CAN ATTRIBUTE (daemon booted on {BOOT_SHA}):")
    for item in LIVE_IN_WINDOW:
        print(f"  live     {item}")
    for item in NOT_IN_WINDOW:
        print(f"  NOT live {item}")
    print("  Anything in the second list cannot have caused a change seen here. The daemon\n"
          "  does not live-reload; a later restart starts a NEW window and this map must be\n"
          "  updated from the new boot record's git_sha before the next reading.\n")

    hyps = [json.loads(r["hypothesis"] or "{}") for r in rows]
    proposals = len(hyps)

    print("PROPOSAL SHAPE (what the loop is generating)")
    cat = sum(1 for h in hyps if CATEGORY.search(h.get("hypothesis_name", "")))
    rate("category-error names", cat, proposals, "category_error_rate")
    filled = sum(1 for h in hyps if str(h.get("learnable_parameters") or "").strip())
    if proposals < MIN_N:
        print(f"  {'learnable_parameters filled':34s} INSUFFICIENT n "
              f"({proposals} of {MIN_N} needed)   [field is new; no pre-restart baseline]")
    else:
        print(f"  {'learnable_parameters filled':34s} {filled}/{proposals} = "
              f"{100.0*filled/proposals:.0f}%   [field is new; no pre-restart baseline]")

    print("\nCANDIDATE CAPACITY (of those that passed validation)")
    validated: List[int] = []
    for r in rows:
        try:
            impl = json.loads(r["implementation"] or "{}")
        except Exception:
            continue
        if not impl.get("validation", {}).get("ok"):
            continue
        n = n_params_of(impl)
        if n is not None:
            validated.append(n)
    zero = sum(1 for n in validated if n == 0)
    rate("zero learnable parameters", zero, len(validated), "zero_param_rate")

    print("\nWHERE CANDIDATES DIE (genuine validation failures)")
    lv: collections.Counter = collections.Counter()
    for r in rows:
        if r["state"] != "failed_validation":
            continue
        try:
            hist = json.loads(r["implementation"] or "{}").get("validation", {}).get("history", [])
        except Exception:
            hist = []
        if any(isinstance(e, dict) and e.get("corrector_error") for e in hist):
            continue                      # infrastructure, not the candidate (§5.3.R4)
        f = r["failure"] or ""
        if "at '" in f:
            lv[f.split("at '")[1].split("'")[0]] += 1
    total = sum(lv.values())
    rate("dry_run share", lv.get("dry_run", 0), total, "dry_run_share")
    if total:
        print(f"      breakdown: {dict(lv.most_common())}")
    # Stages added 2026-07-20 have no pre-restart comparator by construction.
    new_stages = {k: v for k, v in lv.items()
                  if k in ("integration_width", "residual_stream")}
    print(f"      caught by stages added tonight: {new_stages or 'none yet'}")

    print("\nOUTCOMES")
    print(f"  {dict(collections.Counter(r['state'] for r in rows))}")
    print("\nNo claim is made here about causation. A flat rate with a higher rejection "
          "count means the gates work and the proposals did not change — a different "
          "result from the gates not working, and both are worth knowing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
