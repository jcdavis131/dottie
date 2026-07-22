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


# The org's REAL global fleet (rung 6): the operator's deployed sites, probed
# for liveness so the game's Earth board shows genuine field-office status.
SITES = [
    ("hub", "https://dumbmodel.com"),
    ("hoops", "https://hoops.jcamd.com"),
    ("grid", "https://gridiron.dumbmodel.com"),
    ("pitch", "https://pitch.jcamd.com"),
    ("equi", "https://equities.jcamd.com"),
    ("arcad", "https://arcade.dumbmodel.com"),
    ("arxiv", "https://arxiviq.com"),
    ("bhenre", "https://www.bhenre.com"),
]


def _probe_sites() -> list:
    out = []
    for name, url in SITES:
        t0 = time.time()
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=8) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception:
            code = None
        out.append({"name": name, "url": url, "http": code,
                    "ms": round((time.time() - t0) * 1000),
                    "up": bool(code and 200 <= code < 400)})
    return out


# Decode a REAL example from the shard the trainer has claimed right now
# (manifest state CLAIMED_TRAIN; falls back to newest CONSUMED). Runs inside
# the trainer container where the tokenizer + packed volumes live. The doc
# index rotates once per publish window so the console shows fresh examples.
_SAMPLE_SCRIPT = r"""
import json, sqlite3, time
import numpy as np
from dottie.tokenizer import DottieTokenizer
db = sqlite3.connect("/state/manifest.db"); db.row_factory = sqlite3.Row
row = db.execute(
    "select * from shards where state='CLAIMED_TRAIN' order by updated_at desc limit 1"
).fetchone() or db.execute(
    "select * from shards where state='CONSUMED' order by updated_at desc limit 1"
).fetchone()
if not row:
    print(json.dumps({"unreachable": "no CLAIMED_TRAIN/CONSUMED shard in manifest"})); raise SystemExit
idx = json.load(open(str(row["path"]).replace(".bin", ".idx.json")))
docs = idx["docs"]
d = docs[int(time.time() // 600) % len(docs)]
arr = np.memmap(row["path"], dtype=np.uint16, mode="r")
ids = arr[d["start"]: min(d["end"], d["start"] + 160)].tolist()
text = DottieTokenizer.load().decode(ids)
print(json.dumps({
    "shard": row["id"], "source": row["source"], "phase": row["phase"],
    "state": row["state"], "docs_in_shard": len(docs),
    "doc_id": d.get("doc_id"), "task_type": d.get("task_type"),
    "doc_tokens": d["end"] - d["start"], "shown_tokens": len(ids),
    "text": text[:700],
}))
"""


def _batch_sample() -> dict:
    try:
        p = subprocess.run(
            ["docker", "exec", "dottie-factory-trainer-1", "python", "-c", _SAMPLE_SCRIPT],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=45,
        )
        if p.returncode != 0:
            return {"unreachable": (p.stderr or "sample exec failed")[:200]}
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as e:  # noqa: BLE001 - publisher must never crash on a probe
        return {"unreachable": f"{type(e).__name__}: {e}"}


def _site_history(existing_hub, probes: list) -> dict:
    """Rolling 24h of real probe results per site (steer directive 2026-07-22:
    'the console shows trends, not just now'). Carried through the existing
    file across publishes; pruned by wall clock; capped defensively."""
    prev = existing_hub.get("site_history", {}) if isinstance(existing_hub, dict) else {}
    now = time.time()
    hist = {}
    for p in probes:
        rows = [r for r in prev.get(p["name"], [])
                if isinstance(r, dict) and now - r.get("t", 0) < 86400]
        rows.append({"t": round(now), "up": p["up"], "ms": p["ms"]})
        hist[p["name"]] = rows[-160:]
    return hist


def _fleet_snapshot() -> dict:
    """Real docker-stats snapshot for the game's fleet NPCs (2026-07-22).
    Raw docker JSONL rows, parsed client-side; unreachable is honest."""
    try:
        p = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        if p.returncode != 0:
            return {"unreachable": (p.stderr or "docker stats failed")[:200]}
        containers = []
        for line in p.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            containers.append({
                "Name": d.get("Name") or d.get("Container"),
                "CPUPerc": d.get("CPUPerc"),
                "MemPerc": d.get("MemPerc"),
                "MemUsage": d.get("MemUsage"),
            })
        return {"containers": containers}
    except Exception as e:  # noqa: BLE001 - publisher must never crash on a probe
        return {"unreachable": f"{type(e).__name__}: {e}"}


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
        "fleet": _fleet_snapshot(),
        "sites": _probe_sites(),
        "batch_sample": _batch_sample(),
    }
    hub["site_history"] = _site_history(existing.get("hub", {}), hub["sites"])
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
