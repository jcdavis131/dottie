"""Real tool-branch eval gate: base_final vs tool_final on held-out val shards.

Measures, per checkpoint, with NO mocks and NO manifest mutation (read-only
sqlite; val shards are never claimed):

  * planner-argmax rate on tool_selection windows — the router should send tool
    prompts to the planner (SPACES index 3; tool_selection target [.10,.35,.10,.45])
  * held-out CE on the tool_selection mix
  * held-out CE on the general mix (automatic/deliberate/temporal/safety)

Gate rule (TODOS 1.2.c): the tool branch passes iff it beats base on BOTH tool
metrics and general-mix CE regresses <= 2%.

Run inside the trainer image (paths default to the container mounts):

    python -m evals.tool_gate --base-ckpt /ckpt/base_final.pt \
        --tool-ckpt /ckpt/tool/tool_final.pt --device cuda
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch
import torch.nn.functional as F

from dottie.config import SPACES, DottieConfig
from dottie.data import _LoadedShard
from dottie.model import build_model

PLANNER_IDX = SPACES.index("planner")
TOOL_TASKS = ("tool_selection",)
GENERAL_TASKS = ("automatic", "deliberate", "temporal", "safety")


def collect_windows(db_path: str, seq: int, per_task: int, seed: int,
                    log=print) -> dict[str, list[np.ndarray]]:
    """Fixed, seed-stable window sets per task_type from PACKED val shards."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT path FROM shards WHERE split='val' AND state='PACKED' ORDER BY path"
    ).fetchall()
    con.close()

    wanted = list(TOOL_TASKS + GENERAL_TASKS)
    out: dict[str, list[np.ndarray]] = {t: [] for t in wanted}
    rng = random.Random(seed)
    for r in rows:
        p = Path(r["path"])
        if not p.exists():
            continue
        if all(len(out[t]) >= per_task for t in wanted):
            break
        try:
            shard = _LoadedShard(SimpleNamespace(path=str(p)))
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            log(f"skip {p.name}: {exc}")
            continue
        for t in wanted:
            need = per_task - len(out[t])
            if need <= 0:
                continue
            for w, _concept in shard.windows(t, seq, rng):
                out[t].append(np.asarray(w, dtype=np.int64))
                need -= 1
                if need <= 0:
                    break
    for t in wanted:
        log(f"val windows {t}: {len(out[t])}")
    return out


@torch.no_grad()
def eval_ckpt(ckpt: str, cfg: DottieConfig, windows: dict[str, list[np.ndarray]],
              device: str, batch: int = 8, log=print) -> dict:
    model = build_model(cfg).to(device)
    blob = torch.load(ckpt, map_location="cpu", weights_only=False)
    model.load_state_dict(blob["model"])
    model.eval()
    log(f"loaded {ckpt} (step {blob.get('step')})")

    def run_task(task: str) -> tuple[float, float]:
        """(mean CE per token, planner-argmax rate) over this task's windows."""
        ws = windows[task]
        ce_sum = tok_sum = 0.0
        planner_hits = row_count = 0
        for i in range(0, len(ws), batch):
            ids = torch.from_numpy(np.stack(ws[i:i + batch])).to(device)
            ctx = (torch.autocast("cuda", dtype=torch.bfloat16)
                   if device.startswith("cuda") else torch.autocast("cpu", enabled=False))
            with ctx:
                out = model(input_ids=ids[:, :-1], task_type=task)
            logits = out["lm_logits"].float()
            tgt = ids[:, 1:]
            ce = F.cross_entropy(logits.reshape(-1, logits.shape[-1]),
                                 tgt.reshape(-1), reduction="sum")
            ce_sum += float(ce)
            tok_sum += tgt.numel()
            rp = out["jspace"]["route_probs"]        # [B, len(SPACES)]
            planner_hits += int((rp.argmax(-1) == PLANNER_IDX).sum())
            row_count += rp.shape[0]
        return (ce_sum / max(tok_sum, 1), planner_hits / max(row_count, 1))

    res: dict = {"ckpt": ckpt, "step": blob.get("step")}
    if windows["tool_selection"]:
        tool_ce, tool_planner = run_task("tool_selection")
        res["tool_ce"] = round(tool_ce, 5)
        res["tool_planner_rate"] = round(tool_planner, 4)

    gen_ces = []
    for t in GENERAL_TASKS:
        if windows[t]:
            ce, planner = run_task(t)
            res[f"ce_{t}"] = round(ce, 5)
            res[f"planner_rate_{t}"] = round(planner, 4)   # routing sanity per task
            gen_ces.append(ce)
    res["general_ce"] = round(sum(gen_ces) / len(gen_ces), 5) if gen_ces else None

    del model
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="evals.tool_gate", description=__doc__)
    ap.add_argument("--preset", default="mini")
    ap.add_argument("--base-ckpt", default="/ckpt/base_final.pt")
    ap.add_argument("--tool-ckpt", default="/ckpt/tool/tool_final.pt")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--db", default="/state/manifest.db")
    ap.add_argument("--seq", type=int, default=512)
    ap.add_argument("--windows", type=int, default=48, help="windows per task_type")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--out", default="/reports/tool_gate.json")
    args = ap.parse_args(argv)

    torch.manual_seed(args.seed)
    cfg = DottieConfig.load(args.preset)
    windows = collect_windows(args.db, args.seq, args.windows, args.seed)

    # Honest degradation: the pre-reconciliation corpus has NO tool_selection-labeled
    # docs anywhere (measured 2026-07-20: metrics history shows zero tool batches ever
    # trained; val census shows zero tool docs). Until the 2.1 rebuild's sources land,
    # the tool-capability half of this gate is UNMEASURABLE — so it is reported as
    # exactly that, never inferred from proxies. The general-mix non-regression half
    # still runs and is labeled as the only thing it is.
    full_gate = bool(windows["tool_selection"])
    if not full_gate:
        print("WARNING: no tool_selection val windows exist — running NONREGRESSION-ONLY "
              "mode (tool-capability checks reported as unmeasured, verdict.pass=null)")

    base = eval_ckpt(args.base_ckpt, cfg, windows, args.device)
    tool = eval_ckpt(args.tool_ckpt, cfg, windows, args.device)

    gen_reg_pct = (None if not (base.get("general_ce") and tool.get("general_ce"))
                   else (tool["general_ce"] - base["general_ce"]) / base["general_ce"] * 100)
    checks: dict[str, bool] = {
        "general_regression_ok": gen_reg_pct is not None and gen_reg_pct <= 2.0,
    }
    if full_gate:
        checks["tool_ce_improved"] = tool["tool_ce"] < base["tool_ce"]
        checks["planner_rate_improved"] = (
            tool["tool_planner_rate"] >= base["tool_planner_rate"])
    verdict = {
        "mode": "full" if full_gate else "nonregression_only",
        "pass": all(checks.values()) if full_gate else None,
        "nonregression_ok": checks["general_regression_ok"],
        "checks": checks,
        "unmeasured": [] if full_gate else ["tool_ce", "tool_planner_rate"],
        "general_regression_pct": None if gen_reg_pct is None else round(gen_reg_pct, 2),
        "measured": True,
        "ts": time.time(),
        "config": {"seq": args.seq, "windows_per_task": args.windows,
                   "seed": args.seed, "preset": args.preset},
    }
    report = {"base": base, "tool": tool, "verdict": verdict}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if verdict["pass"] is None:
        outcome = ("NONREGRESSION-ONLY: "
                   + ("clean" if verdict["nonregression_ok"] else "REGRESSED"))
        code = 3 if verdict["nonregression_ok"] else 1
    else:
        outcome = "PASS" if verdict["pass"] else "FAIL"
        code = 0 if verdict["pass"] else 1
    print(f"wrote {args.out} — gate {outcome}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
