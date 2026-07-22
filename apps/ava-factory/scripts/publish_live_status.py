# Solo personal project, no connection to employer, built with public/free-tier only
"""Publish the live status snapshot to the arxiviq Control Plane — hygiene-compatible.

The monorepo (correctly) gitignores telemetry, so the site can no longer read a
committed STATUS.json from the code repo; the legacy-repo fallback froze at the
cutover. This publisher closes the gap without violating hygiene: compose a fresh
snapshot (factory /pipeline/status + research /research status.json + whatever the
local reports file already holds), write reports/dottie_live_status.json (gitignored),
and push it to a GitHub GIST (free tier) that app.js reads first.

Setup (once):  gh gist create reports/dottie_live_status.json --public
               setx DOTTIE_STATUS_GIST <gist-id>     (or pass --gist)
Cron:          python scripts/publish_live_status.py --gist <id>

Every value is fetched or carried, never invented: unreachable sources are recorded
as {"unreachable": reason} blocks so the site shows honest gaps, not stale numbers.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "reports" / "dottie_live_status.json"


def _get_json(url: str, timeout: float = 10.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"unreachable": f"{type(e).__name__}: {e}", "url": url}


def compose() -> dict:
    existing = {}
    if OUT.exists():
        try:
            existing = json.loads(OUT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    pipeline = _get_json("http://localhost:8000/pipeline/status")
    research_path = REPO.parent / "dottie" / "data" / "research" / "status.json"
    try:
        research = json.loads(research_path.read_text(encoding="utf-8"))
    except Exception as e:
        research = {"unreachable": f"{type(e).__name__}: {e}"}
    # The rest of the :8000 hub, snapshotted for the public twin (operator
    # 2026-07-22: "bring all of localhost:8000 live to bluehenre.com"). Each
    # panel is the endpoint's real JSON or an honest {"unreachable": ...}.
    # ~12KB combined — negligible next to the pipeline block.
    hub = {
        "network": _get_json("http://localhost:8000/network/status"),
        "ecosystem": _get_json("http://localhost:8000/ecosystem/status"),
        "agent_eval": _get_json("http://localhost:8000/agent_eval/scoreboard"),
        "eval_report": _get_json("http://localhost:8000/jspace/eval_report"),
        "eval_catalog": _get_json("http://localhost:8000/jspace/eval_catalog"),
    }
    snapshot = {
        **existing,
        "schema": "dottie_live_status/v2",  # additive: v2 consumers unaffected by "hub"
        "published_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "publish_live_status.py on the 4080 box (gist; repo telemetry stays gitignored)",
        "pipeline": pipeline,
        "research": research,
        "hub": hub,
    }
    return snapshot


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--gist",
        default=os.environ.get("DOTTIE_STATUS_GIST"),
        help="gist id to update (omit to only write the local file)",
    )
    args = ap.parse_args(argv)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    snap = compose()
    OUT.write_text(json.dumps(snap, indent=2), encoding="utf-8")
    result = {
        "ok": True,
        "wrote": str(OUT),
        "pipeline_live": "unreachable" not in snap["pipeline"],
        "research_live": "unreachable" not in snap["research"],
    }
    if args.gist:
        p = subprocess.run(
            ["gh", "gist", "edit", args.gist, "--add", str(OUT)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        result["gist"] = args.gist
        result["published"] = p.returncode == 0
        if p.returncode != 0:
            result["ok"] = False
            result["error"] = (p.stderr or p.stdout)[:300]
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
