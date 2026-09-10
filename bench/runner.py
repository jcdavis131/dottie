#!/usr/bin/env python3
"""Dottie benchmark runner — stdlib-only, parallel, dry-run/read-only.

Runs every workflow in bench/workflow_inventory.json as a subprocess,
measures wall latency, exit code, output size, and a heuristic token
estimate (chars/4 — labeled as estimate, never as metered usage), then
applies a per-workflow correctness checker.

Usage:
    python3 bench/runner.py [--only ID] [--max-workers N] [--out DIR] [--timeout-scale F]

Output: <out>/results.json — one record per workflow run.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path.home() / "workspace" / "dottie"


def expand(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(p)))


# ---------------------------------------------------------------- checkers

def _json_stdout(res):
    try:
        return json.loads(res["stdout"])
    except Exception as e:
        return {"_parse_error": str(e)}


def check_goal_intake(res):
    ok = res["exit_code"] == 0
    return ok, ("drain ran read-only, no exception" if ok
                else f"drain failed: exit={res['exit_code']} {res['stderr_tail'][:200]}")


def check_playbook_dryrun(res):
    ok = res["exit_code"] == 0 and "WOULD-WRITE" in res["stdout"]
    detail = "would-write artifacts reported" if ok else \
        f"exit={res['exit_code']} stdout={res['stdout'][:200]!r}"
    return ok, detail


def check_playbook_validation(res):
    ok = res["exit_code"] == 0 and ("skip" in res["stdout"].lower()
                                    or "WOULD-WRITE" in res["stdout"])
    return ok, ("honest absence reported (skipped-missing-input)" if ok
                else f"exit={res['exit_code']} {res['stdout'][:200]!r}")


def check_retrieval_json(res):
    if res["exit_code"] != 0:
        return False, f"exit={res['exit_code']} {res['stderr_tail'][:200]}"
    d = _json_stdout(res)
    if "_parse_error" in d:
        return False, f"stdout not JSON: {d['_parse_error']}"
    base = d.get("baseline_on_test", {})
    if base:  # commit-shaped slice
        allm, leak = base.get("all", {}), base.get("leak_free", {})
        detail = (f"ndcg={allm.get('ndcg')} leak_free_ndcg={leak.get('ndcg')} "
                  f"n={base.get('n')} hit_rate={base.get('hit_rate_all')}")
    else:  # task-shaped slice
        ts = d.get("task_slice", {}).get("metrics", {}).get("all", {})
        verdict = d.get("verdict", {})
        detail = (f"task ndcg={ts.get('ndcg')} commit ndcg={verdict.get('ndcg', {}).get('commit')}"
                  f" hypothesis_held={verdict.get('hypothesis_held')}")
    return True, detail


def check_gate_audit(res):
    out = res.get("stdout", "") or res.get("stdout_head", "")
    m = re.search(r"gate audit:\s*(\d+)\s+NEW candidate", out)
    new_n = int(m.group(1)) if m else None
    files = re.findall(r"^\s{2}(\S+:\d+)", out, re.M)
    if res["exit_code"] not in (0, 1):
        return False, f"exit={res['exit_code']} {res['stderr_tail'][:200]}"
    if new_n:
        return True, (f"audit ran: {new_n} NEW un-baselined candidates "
                      f"({'; '.join(files[:4])}) — human judgement pending")
    return True, "audit ran: all candidates baselined"


def check_grpo_collect(res):
    outdir = Path(res.get("outdir", ""))
    want = ["trace_bank.jsonl", "pref_pairs.jsonl",
            "grpo_group_stats.jsonl", "MANIFEST.json"]
    missing = [w for w in want if not (outdir / "grpo" / w).exists()]
    if res["exit_code"] != 0:
        return False, f"exit={res['exit_code']} {res['stderr_tail'][:200]}"
    if missing:
        return False, f"missing outputs: {missing}"
    synth = "synthetic=True" in res["stdout"] or "synthetic" in res["stdout"].lower()
    note = "outputs valid" + ("; WARNING: run flagged synthetic=True (data-quality caveat)"
                              if synth else "")
    return True, note


def check_goldens(res):
    ok = res["exit_code"] == 0 and "GOLDENS_OK" in res["stdout"]
    return ok, (res["stdout"].strip()[:120] if ok
                else f"exit={res['exit_code']} {res['stderr_tail'][:200]}")


CHECKERS = {k: v for k, v in list(globals().items()) if k.startswith("check_")}


# ---------------------------------------------------------------- runner

def run_one(wf, outdir: Path, timeout_scale: float):
    cmd = [a.replace("{OUTDIR}", str(outdir)) for a in wf["command"]]
    cwd = expand(wf.get("cwd", str(REPO)))
    timeout = wf.get("timeout_s", 180) * timeout_scale
    rec = {"id": wf["id"], "name": wf["name"], "category": wf.get("category"),
           "command": cmd, "timeout_s": timeout, "status": "ran"}
    if not cwd.exists():
        rec.update(status="blocked", ok=False,
                   correctness=f"BLOCKED: cwd missing: {cwd}")
        return rec
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout)
        wall_ms = (time.monotonic() - t0) * 1000
        out, err = p.stdout or "", p.stderr or ""
        rec.update(exit_code=p.returncode, latency_ms=round(wall_ms, 1),
                   stdout=out, stderr_tail=err[-2000:],
                   stdout_chars=len(out), stderr_chars=len(err),
                   tokens_est=math.ceil((len(out) + len(err)) / 4))
    except subprocess.TimeoutExpired as e:
        wall_ms = (time.monotonic() - t0) * 1000
        rec.update(status="blocked", ok=False, latency_ms=round(wall_ms, 1),
                   correctness=f"BLOCKED: timed out after {timeout:.0f}s",
                   stdout=(e.stdout or ""), stderr_tail=str(e.stderr or "")[-500:],
                   tokens_est=0)
        return rec
    except FileNotFoundError as e:
        rec.update(status="blocked", ok=False,
                   correctness=f"BLOCKED: executable missing: {e}")
        return rec
    except Exception as e:
        rec.update(status="blocked", ok=False,
                   correctness=f"BLOCKED: {type(e).__name__}: {e}")
        return rec
    checker = CHECKERS.get(wf.get("checker", ""))
    rec["outdir"] = str(outdir)
    if checker is None:
        rec.update(ok=False, correctness=f"BLOCKED: no checker named {wf.get('checker')}")
    else:
        try:
            ok, detail = checker(rec)
            rec.update(ok=bool(ok), correctness=detail)
        except Exception as e:
            rec.update(ok=False, correctness=f"CHECKER_ERROR {type(e).__name__}: {e}")
    # keep payloads small: drop full stdout, keep a head for debugging
    rec["stdout_head"] = rec.pop("stdout", "")[:1500]
    return rec


def main():
    ap = argparse.ArgumentParser(description="Dottie benchmark runner (dry-run/read-only)")
    ap.add_argument("--only", help="run a single workflow id")
    ap.add_argument("--max-workers", type=int, default=4)
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--timeout-scale", type=float, default=1.0)
    args = ap.parse_args()

    inv = json.loads((HERE / "workflow_inventory.json").read_text())
    wfs = inv["workflows"]
    if args.only:
        wfs = [w for w in wfs if w["id"] == args.only]
        if not wfs:
            sys.exit(f"unknown workflow id: {args.only}")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="dottie_bench_", dir=str(outdir)))

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.max_workers) as ex:
        results = list(ex.map(lambda w: run_one(w, tmpdir, args.timeout_scale), wfs))
    total_ms = (time.monotonic() - t0) * 1000

    payload = {"mode": inv.get("mode"), "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "wall_ms": round(total_ms, 1), "results": results}
    (outdir / "results.json").write_text(json.dumps(payload, indent=2))
    ok_n = sum(1 for r in results if r.get("ok"))
    blocked_n = sum(1 for r in results if r.get("status") == "blocked")
    print(f"bench: {ok_n}/{len(results)} ok, {blocked_n} blocked, wall={total_ms/1000:.1f}s")
    print(f"bench: wrote {outdir / 'results.json'}")
    for r in results:
        mark = "OK " if r.get("ok") else ("BLOCK" if r.get("status") == "blocked" else "FAIL")
        print(f"  [{mark}] {r['id']:20s} {r.get('latency_ms','?'):>10}ms  {r.get('correctness','')[:90]}")


if __name__ == "__main__":
    main()
