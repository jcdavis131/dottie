# Solo personal project, no connection to employer, built with public/free-tier only
"""Hardened successor to publish_live_status.py — STAGED COPY, not yet scheduled.

The live file (publish_live_status.py) is executed every 10 min by the
"Dottie Status publisher" Task Scheduler job and must never be edited in place;
the main loop swaps this copy in later. Changes over the live version:

  * gist push is crash-proof: gh-CLI-absent (FileNotFoundError) or gh-hung
    (TimeoutExpired) no longer aborts the run after OUT is written; 3 attempts
    with exponential backoff, final failure lands in-band in the result JSON.
  * stale markers on carried sections: site_perf gains "carried"/"carried_age_s"
    when the weekly block is reused, failed site probes gain "err", and legacy
    top-level keys respread from the previous snapshot are listed under
    "carried_from_previous". All additive — hosted parsers (bluehenre twin.mjs,
    arxiviq app.js) read known fields only and need no changes.
  * stderr breadcrumbs on every swallowed exception (Task Scheduler discards
    stdio, but console runs and any future logging wrapper see the trace).
  * --dry-run/--offline builds the full payload with zero network/subprocess
    calls, writes dottie_live_status_next_dryrun.json, and never pushes.

Feed schema and live behavior are otherwise IDENTICAL to the live publisher.

Original operating notes:

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
DRYRUN_OUT = REPO / "reports" / "dottie_live_status_next_dryrun.json"

OFFLINE = False  # set by --dry-run/--offline: no sockets, no subprocesses

GIST_ATTEMPTS = 3
GIST_BACKOFF_S = 3.0  # doubles between attempts: 3s, then 6s


def _breadcrumb(msg: str) -> None:
    # Task Scheduler discards stderr, but console runs (and a future logging
    # wrapper) get an in-order trace of every failure the feed swallows.
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"[publish_live_status_next] {ts} {msg}", file=sys.stderr)


def _get_json(url: str, timeout: float = 10.0):
    if OFFLINE:
        return {"unreachable": "offline (--dry-run): network disabled", "url": url}
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        _breadcrumb(f"_get_json {url}: {type(e).__name__}: {e}")
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
    if OFFLINE:
        # keep the list shape (_site_history iterates it); rows are honest skips
        return [{"name": name, "url": url, "http": None, "ms": 0, "up": False,
                 "err": "offline (--dry-run)"} for name, url in SITES]
    out = []
    for name, url in SITES:
        t0 = time.time()
        err = None
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=8) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception as e:
            code = None
            err = type(e).__name__  # additive: DNS vs TLS vs timeout visible in trends
            _breadcrumb(f"_probe_sites {name} {url}: {type(e).__name__}: {e}")
        row = {"name": name, "url": url, "http": code,
               "ms": round((time.time() - t0) * 1000),
               "up": bool(code and 200 <= code < 400)}
        if err:
            row["err"] = err
        out.append(row)
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
    if OFFLINE:
        return {"unreachable": "offline (--dry-run): docker exec skipped"}
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
        _breadcrumb(f"_batch_sample: {type(e).__name__}: {e}")
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


_ANSI_RE = None  # lazy-compiled below


def _deploys_snapshot() -> dict:
    """Read-only deploy recency per Vercel project (steer directive: DEPLOYS
    card). Parses the CLI's human table (no --json exists); ANSI stripped;
    honest unreachable on any failure."""
    global _ANSI_RE
    import re as _re
    if _ANSI_RE is None:
        _ANSI_RE = _re.compile(r"\x1b\[[0-9;]*m")
    if OFFLINE:
        return {"unreachable": "offline (--dry-run): vercel CLI skipped"}
    try:
        vercel_bin = "vercel.cmd" if os.name == "nt" else "vercel"
        p = subprocess.run(
            [vercel_bin, "projects", "ls", "--scope", "cams-projects-c5c4c5f6"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60,
        )
        if p.returncode != 0:
            return {"unreachable": (p.stderr or "vercel ls failed")[:200]}
        projects = []
        # the CLI prints its table on STDERR (stdout stays empty) — parse both
        for line in (p.stdout + "\n" + p.stderr).splitlines():
            clean = _ANSI_RE.sub("", line)
            m = _re.match(r"^\s{2}(\S+)\s+(https://\S+)\s+(\S+)", clean)
            if m and m.group(1) != "Project":
                projects.append({"name": m.group(1), "url": m.group(2),
                                 "updated": m.group(3)})
        return {"projects": projects} if projects else {"unreachable": "no rows parsed"}
    except Exception as e:  # noqa: BLE001 - publisher must never crash on a probe
        _breadcrumb(f"_deploys_snapshot: {type(e).__name__}: {e}")
        return {"unreachable": f"{type(e).__name__}: {e}"}


def _site_perf(existing_hub) -> dict:
    """Weekly TTFB + page-weight per site with >20% regression flags (steer
    directive). Self-scheduling: re-measures only when the carried block is
    older than 6 days; otherwise carries it forward untouched. Real requests,
    honest failures; regressions compare against the PREVIOUS measurement."""
    prev = existing_hub.get("site_perf", {}) if isinstance(existing_hub, dict) else {}
    now = time.time()
    if isinstance(prev.get("measured_at"), (int, float)) and now - prev["measured_at"] < 6 * 86400:
        carried = dict(prev)
        # stale markers (additive): the weekly carry is by-design, but label it
        # so consumers can tell a reused block from a fresh measurement
        carried["carried"] = True
        carried["carried_age_s"] = round(now - prev["measured_at"])
        return carried
    if OFFLINE:
        return {"unreachable": "offline (--dry-run): perf measurement skipped"}
    rows = []
    regressions = []
    prev_rows = {r["name"]: r for r in prev.get("rows", []) if isinstance(r, dict)}
    for name, url in SITES:
        try:
            t0 = time.time()
            with urllib.request.urlopen(url, timeout=15) as r:
                r.read(1)
                ttfb_ms = round((time.time() - t0) * 1000)
                body = r.read()
            page_bytes = len(body) + 1
            row = {"name": name, "ttfb_ms": ttfb_ms, "page_bytes": page_bytes}
            p = prev_rows.get(name)
            for metric, label in (("ttfb_ms", "TTFB"), ("page_bytes", "page weight")):
                if p and isinstance(p.get(metric), (int, float)) and p[metric] > 0:
                    ratio = row[metric] / p[metric]
                    if ratio > 1.2:
                        regressions.append({
                            "name": name, "metric": metric,
                            "label": f"{name} {label} regressed {round((ratio - 1) * 100)}% "
                                     f"({p[metric]} -> {row[metric]})"})
            rows.append(row)
        except Exception as e:  # noqa: BLE001
            _breadcrumb(f"_site_perf {name} {url}: {type(e).__name__}: {e}")
            rows.append({"name": name, "error": f"{type(e).__name__}"[:60]})
    return {"measured_at": round(now), "rows": rows, "regressions": regressions}


def _fleet_snapshot() -> dict:
    """Real docker-stats snapshot for the game's fleet NPCs (2026-07-22).
    Raw docker JSONL rows, parsed client-side; unreachable is honest."""
    if OFFLINE:
        return {"unreachable": "offline (--dry-run): docker stats skipped"}
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
            except json.JSONDecodeError as e:
                _breadcrumb(f"_fleet_snapshot unparseable stats row {line[:80]!r}: {e}")
                continue
            containers.append({
                "Name": d.get("Name") or d.get("Container"),
                "CPUPerc": d.get("CPUPerc"),
                "MemPerc": d.get("MemPerc"),
                "MemUsage": d.get("MemUsage"),
            })
        return {"containers": containers}
    except Exception as e:  # noqa: BLE001 - publisher must never crash on a probe
        _breadcrumb(f"_fleet_snapshot: {type(e).__name__}: {e}")
        return {"unreachable": f"{type(e).__name__}: {e}"}


def compose() -> dict:
    existing = {}
    if OUT.exists():
        try:
            existing = json.loads(OUT.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            _breadcrumb(f"existing snapshot unparseable, composing fresh: {e}")
            existing = {}
    pipeline = _get_json("http://localhost:8000/pipeline/status")
    research_path = REPO.parent / "dottie" / "data" / "research" / "status.json"
    try:
        research = json.loads(research_path.read_text(encoding="utf-8"))
    except Exception as e:
        _breadcrumb(f"research status read {research_path}: {type(e).__name__}: {e}")
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
    hub["deploys"] = _deploys_snapshot()
    hub["site_perf"] = _site_perf(existing.get("hub", {}))
    snapshot = {
        **existing,
        "schema": "dottie_live_status/v2",  # additive: v2 consumers unaffected by "hub"
        "published_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "publish_live_status.py on the 4080 box (gist; repo telemetry stays gitignored)",
        "pipeline": pipeline,
        "research": research,
        "hub": hub,
    }
    # stale marker (additive): the **existing respread keeps legacy top-level
    # keys (updated_at/run_id/counts/...) alive under a fresh published_utc;
    # list them so consumers can tell carried from fresh. Recomputed each run.
    snapshot.pop("carried_from_previous", None)
    fresh_keys = {"schema", "published_utc", "source", "pipeline", "research",
                  "hub", "carried_from_previous"}
    carried_keys = sorted(k for k in existing if k not in fresh_keys)
    if carried_keys:
        snapshot["carried_from_previous"] = {
            "keys": carried_keys,
            "note": "top-level fields carried unchanged from the prior snapshot, "
                    "not refreshed this run",
        }
    return snapshot


def _push_gist(gist_id: str) -> dict:
    """gh gist edit with retry + exponential backoff. In the live publisher the
    push is the one uncaught-crash path (gh absent -> FileNotFoundError, gh
    hung -> TimeoutExpired after OUT is written, freezing the gist silently);
    here every failure lands in-band in the result instead."""
    delay = GIST_BACKOFF_S
    last_err = ""
    for attempt in range(1, GIST_ATTEMPTS + 1):
        try:
            p = subprocess.run(
                ["gh", "gist", "edit", gist_id, "--add", str(OUT)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            if p.returncode == 0:
                return {"published": True, "attempts": attempt}
            last_err = (p.stderr or p.stdout)[:300]
        except Exception as e:  # noqa: BLE001 - a failed push must not crash the run
            last_err = f"{type(e).__name__}: {e}"[:300]
        _breadcrumb(f"gist push attempt {attempt}/{GIST_ATTEMPTS} failed: {last_err}")
        if attempt < GIST_ATTEMPTS:
            time.sleep(delay)
            delay *= 2
    return {"published": False, "attempts": GIST_ATTEMPTS, "error": last_err}


def main(argv=None) -> int:
    global OFFLINE
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--gist",
        default=os.environ.get("DOTTIE_STATUS_GIST"),
        help="gist id to update (omit to only write the local file)",
    )
    ap.add_argument(
        "--dry-run", "--offline",
        action="store_true",
        dest="dry_run",
        help="build the full payload with no network/subprocess calls, write "
             "dottie_live_status_next_dryrun.json, never push the gist",
    )
    args = ap.parse_args(argv)
    OFFLINE = args.dry_run
    out_path = DRYRUN_OUT if args.dry_run else OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    snap = compose()
    out_path.write_text(json.dumps(snap, indent=2), encoding="utf-8")
    result = {
        "ok": True,
        "wrote": str(out_path),
        "pipeline_live": "unreachable" not in snap["pipeline"],
        "research_live": "unreachable" not in snap["research"],
    }
    if args.dry_run:
        result["dry_run"] = True
        result["sections"] = sorted(snap.keys())
        result["hub_sections"] = sorted(snap["hub"].keys())
    elif args.gist:
        push = _push_gist(args.gist)
        result["gist"] = args.gist
        result["published"] = push["published"]
        result["gist_attempts"] = push["attempts"]
        if not push["published"]:
            result["ok"] = False
            result["error"] = push["error"]
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
