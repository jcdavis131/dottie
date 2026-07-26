#!/usr/bin/env python3
# Solo personal project, no connection to employer, built with public/free-tier only.
"""Training-leg history: trainer metrics -> runtrack.db -> static Monitor readout.

The Monitor pillar's cross-run view. The trainer's metrics jsonl is an append-only
log spanning several training LEGS (each schedule extension resumes the branch and
adds a leg). This segments it on the trainer's own `branch_forked` / `resumed` /
`done` events, logs every leg's real measured step metrics into the `runtrack`
sqlite tracker (scout-cli's W&B-lite core -- no server, no egress), and exports a
static readout the site renders.

Provenance doctrine: every value is the trainer's own logged measurement. Nothing
is smoothed, imputed, or invented; a leg with no measured steps is dropped rather
than shown empty. The LIVE current-run numbers stay on the feed -- this readout is
labelled history.

Usage (metrics live in the ava_reports docker volume, so extract first):
  docker exec dottie-factory-trainer-1 cat /reports/metrics_mini.jsonl > m.jsonl
  python build_training_runs.py --metrics m.jsonl \
      --db apps/dottie/data/runtrack.db --out apps/bluehenre/public/training_runs.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "apps" / "scout-cli"))
from bigbang.core import runtrack

# events that begin a new training leg / end one
_LEG_START = ("branch_forked", "resumed")
_LEG_END = ("done",)


def segment_legs(path: Path) -> list[dict]:
    """Split the metrics log into legs of contiguous measured steps.

    Returns [{start_event, steps: [{step, lm, tok_s, phase, tokens, ts}]}], in file
    order. Malformed lines are skipped (the log interleaves many event types).
    """
    legs: list[dict] = []
    cur: dict | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        ev = d.get("event")
        if ev in _LEG_START:
            cur = {"start_event": ev, "steps": []}
            legs.append(cur)
            continue
        if ev in _LEG_END:
            cur = None
            continue
        if ev != "step":
            continue
        step, lm = d.get("step"), d.get("lm")
        if not isinstance(step, int) or not isinstance(lm, (int, float)):
            continue
        if cur is None:  # steps before any start event = the original leg
            cur = {"start_event": "initial", "steps": []}
            legs.append(cur)
        cur["steps"].append(
            {
                "step": step,
                "lm": float(lm),
                "tok_s": d.get("tok_s"),
                "phase": d.get("phase"),
                "tokens": d.get("tokens"),
                "ts": d.get("ts"),
            }
        )
    return [lg for lg in legs if lg["steps"]]  # a leg with no measurement is dropped


def leg_name(idx: int, lg: dict) -> str:
    """STABLE identity for a leg: keyed on its FIRST step only.

    Deliberately excludes the last step: the live leg grows on every ingest, and a
    range-based name ("steps 2870-2910") would mint a NEW runtrack run each time,
    duplicating history. Keyed on the start, re-ingesting the same leg resolves to
    the same run and only its new steps are appended.
    """
    return f"leg from step {lg['steps'][0]['step']}"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Ingest trainer legs into runtrack + export a readout."
    )
    ap.add_argument("--metrics", required=True, help="trainer metrics jsonl")
    ap.add_argument(
        "--db", required=True, help="runtrack sqlite db (created if absent)"
    )
    ap.add_argument("--out", help="static readout json to write (optional)")
    ap.add_argument(
        "--curve-points", type=int, default=60, help="max curve points per leg"
    )
    # The metrics log is append-only across this factory's WHOLE history and a
    # `resumed` event fires on every container restart, so raw segmentation yields
    # dozens of 1-10 step fragments with overlapping ranges. These two filters keep
    # the readout to substantive, non-duplicated legs; both are reported in the
    # readout so the drop is visible rather than silent.
    ap.add_argument(
        "--min-steps",
        type=int,
        default=20,
        help="drop legs with fewer measured steps (restart fragments)",
    )
    ap.add_argument(
        "--last", type=int, default=8, help="keep only the N most recent legs"
    )
    args = ap.parse_args()

    all_legs = segment_legs(Path(args.metrics))
    substantive = [lg for lg in all_legs if len(lg["steps"]) >= args.min_steps]
    # drop a leg whose step range is fully contained in a later leg's (restart replay)
    deduped = []
    for i, lg in enumerate(substantive):
        lo, hi = lg["steps"][0]["step"], lg["steps"][-1]["step"]
        if any(
            o["steps"][0]["step"] <= lo
            and o["steps"][-1]["step"] >= hi
            and len(o["steps"]) > len(lg["steps"])
            for o in substantive[i + 1 :]
        ):
            continue
        deduped.append(lg)
    # ALWAYS keep the newest leg even if it is still short: it is the run training
    # right now, and a young leg is the most interesting one to watch — dropping it
    # for failing a maturity threshold would hide the live run.
    if all_legs and all_legs[-1] not in deduped:
        deduped.append(all_legs[-1])
    dropped = len(all_legs) - len(deduped)
    legs = deduped[-args.last :] if args.last > 0 else deduped
    if not legs:
        print("no measured steps found — nothing ingested", file=sys.stderr)
        return 1

    conn = runtrack.open_store(args.db)
    out_legs = []
    for i, lg in enumerate(legs):
        steps = lg["steps"]
        name = leg_name(i, lg)
        # IDEMPOTENT + INCREMENTAL: reuse the existing run for this leg and append
        # only steps we have not logged yet. Re-running the ingest as training
        # advances must extend history, never duplicate it.
        existing = [r for r in runtrack.list_runs(conn, name=name, limit=1)]
        if existing:
            run_id = int(existing[0]["id"])
            logged = {p["step"] for p in runtrack.run_history(conn, run_id, key="lm")}
        else:
            run = runtrack.start_run(
                conn,
                name,
                config={
                    "start_event": lg["start_event"],
                    "first_step": steps[0]["step"],
                },
                ts=steps[0].get("ts"),
            )
            run_id, logged = int(run["id"]), set()
        for s in steps:
            if s["step"] in logged:
                continue
            metrics = {"lm": s["lm"]}
            if isinstance(s.get("tok_s"), (int, float)):
                metrics["tok_s"] = float(s["tok_s"])
            runtrack.log_metrics(conn, run_id, metrics, step=s["step"], ts=s.get("ts"))
        runtrack.finish_run(conn, run_id, ts=steps[-1].get("ts"))

        lms = [s["lm"] for s in steps]
        stride = max(1, len(steps) // max(1, args.curve_points))
        curve = [
            {"step": s["step"], "lm": round(s["lm"], 4)}
            for j, s in enumerate(steps)
            if j % stride == 0 or j == len(steps) - 1
        ]
        out_legs.append(
            {
                "name": name,
                "start_event": lg["start_event"],
                "first_step": steps[0]["step"],
                "last_step": steps[-1]["step"],
                "measured_steps": len(steps),
                "lm_first": round(lms[0], 4),
                "lm_last": round(lms[-1], 4),
                "lm_min": round(min(lms), 4),
                "tokens_last": steps[-1].get("tokens"),
                "phases": sorted(
                    {s["phase"] for s in steps if isinstance(s.get("phase"), int)}
                ),
                "curve": curve,
            }
        )

    print(
        f"ingested {len(out_legs)} legs into {args.db}: "
        + ", ".join(
            f"{l['name']} (lm {l['lm_first']}->{l['lm_last']})" for l in out_legs
        ),
        file=sys.stderr,
    )

    if args.out:
        doc = {
            "generated_by": "build_training_runs.py",
            "metric": "lm loss per logged training step (trainer's own measurement)",
            # the drop is stated, never silent: the log spans the factory's whole
            # history and every container restart emits a `resumed` fragment
            "segmentation": (
                f"legs delimited by the trainer's own branch_forked/resumed/done "
                f"events; {dropped} restart fragments below {args.min_steps} "
                f"measured steps (or fully replayed by a later leg) dropped; "
                f"showing the {len(out_legs)} most recent of {len(deduped)}"
            ),
            "count": len(out_legs),
            "legs": out_legs,
        }
        Path(args.out).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
