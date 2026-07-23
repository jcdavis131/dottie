# Design: eval gate in checkpoint promotion (monorepo review 2026-07-22, item #2)

Status: L2 design only. `apps/ava-factory` is FROZEN this cycle (`dottie/` + `configs/`
bind-mounted into the live trainer container). Everything below is ready to implement
the hour training ends. No code was changed for this document.

## 1. Current promotion path (verified 2026-07-23, exact files/lines)

All paths relative to `C:\Users\jcdav\dottie\apps\ava-factory`.

| File:line | What it does today |
|---|---|
| `dottie/train.py:194-198` | `_point_latest_at(ckpt_dir, target)` — writes `ckpt/latest` as a **text file** (target filename), atomic via `latest.tmp` + `os.replace` |
| `dottie/train.py:653` | `if step % cfg.training.checkpoint_every_steps == 0 or step == total_steps:` |
| `dottie/train.py:655-665` | `save_ckpt(step_{n}.pt)` then `_point_latest_at(ckpt_dir, p)` — **unconditional**, no eval consulted |
| `dottie/train.py:685-696` | final save (`{branch}_final.pt`) then `_point_latest_at(ckpt_dir, final)` — also unconditional |
| `dottie/serve_engine.py:8-15, 104-115, 211-236` | serve engine hot-reload: when `AVA_CKPT` points at a `latest` pointer file, polls mtime+content every ~5s (`_HOT_RELOAD_INTERVAL_S = 5.0`, line 69) and swaps weights in |
| `docker-compose.yml:156` | serve service: `AVA_CKPT: ${AVA_CKPT:-/ckpt/latest}` — so every checkpoint goes live within ~5s of the pointer moving |
| `evals/run_harness.py:52-105` | `run_harness(preset, base_ckpt, ...)` returns a results dict (perplexity / probes / jspace / needle per branch + meta); per-jspace-test `pass` booleans exist (`_verdict`, lines 35-42) but **no aggregate promote/hold verdict** |
| `evals/run_harness.py:108-155` | `write_reports` OVERWRITES `reports/branch_eval_results_real.json` + `REPORT_REAL.md` on every run (known footgun) |
| `efficiency_gain.py:125-140` | `eg_trend()` emits `"promote"`/`"hold"` — but for scaling-rung EG trends, and it is report-only; grep confirms nothing in the trainer or loop consumes any verdict |
| `configs/mini.yaml:67` | `checkpoint_every_steps: 8` (temporary; comment says RESTORE 50 once the power cap lifts) |

Gap restated: the harness runs and reports, but its verdict changes nothing. A regressed
or corrupted-but-loadable checkpoint is serving traffic ~5s after it is written.

## 2. Design

### 2.1 Two pointers instead of one

- `ckpt/latest_candidate` — moved by the **trainer** after every save (today's behavior, renamed).
- `ckpt/latest` — moved ONLY by the **promotion script** after a promote verdict.
- Same text-file + `.tmp` + `os.replace` mechanics; `serve_engine._resolve_ckpt` needs zero
  changes (it resolves whatever `AVA_CKPT` names; the pointer-file special case keys on the
  basename `latest`, `serve_engine.py:104` — `latest_candidate` would NOT hot-reload, which is
  fine because only the promoter touches `latest`).
- Optional canary: a second serve container with `AVA_CKPT=/ckpt/latest_candidate` — note the
  basename check at `serve_engine.py:104/166/172` means candidate-pointer hot-reload would need
  a serve_engine tweak; defer, not needed for the gate itself.

### 2.2 `dottie/train.py` diff sketch (apply only after training ends)

Env-flag gated so the first container boot after the change behaves identically until the
promoter exists and is enabled. Matches the file's existing env-override style
(`AVA_MAX_MICRO_BATCH` train.py:45, `AVA_CKPT_ROTATE_MIN` train.py:671).

```diff
 def _point_latest_at(ckpt_dir: Path, target: Path) -> None:
-    latest = ckpt_dir / "latest"
-    tmp = ckpt_dir / "latest.tmp"
+    # Gated promotion: when AVA_GATED_PROMOTION=1 the trainer only ever moves
+    # latest_candidate; scripts/promote_ckpt.py owns ckpt/latest (serve target).
+    name = (
+        "latest_candidate"
+        if os.environ.get("AVA_GATED_PROMOTION", "0") == "1"
+        else "latest"
+    )
+    latest = ckpt_dir / name
+    tmp = ckpt_dir / (name + ".tmp")
     tmp.write_text(target.name)
     os.replace(tmp, latest)  # a file, not a symlink: Windows volumes
```

Call sites at train.py:665 and :696 unchanged — the flag flips both periodic and final saves
at once. Rollback = unset the env var.

### 2.3 New file: `scripts/promote_ckpt.py`

Runs in the trainer image (needs torch + evals + the frozen tokenizer). One-shot and
daemon modes. Skeleton:

```python
"""Eval-gated checkpoint promotion. Owns ckpt/latest; trainer owns latest_candidate.

Verdict policy (ppl is the only graded signal at mini scale — probes are 0/200,
documented honest baseline):
  PROMOTE iff (a) candidate loads and harness completes with no branch-level error,
  (b) weighted heldout ppl <= incumbent_ppl * (1 + AVA_PROMOTE_PPL_TOL, default 0.02),
  or there is no incumbent baseline yet (first promotion records the baseline).
  Anything else (harness exception, missing bins, NaN/None ppl) -> HOLD, latest
  untouched, reason logged. Never promote on error — that recreates the old bug.
"""
from __future__ import annotations
import argparse, json, os, time
from pathlib import Path
from evals.run_harness import run_harness

CKPT_DIR = Path(os.environ.get("AVA_CKPT_DIR", "/ckpt"))
LOG = CKPT_DIR / "promotions.jsonl"          # append-only audit trail
BASELINE = CKPT_DIR / "promoted_baseline.json"  # {"ckpt": name, "weighted_ppl": float}

def _read_pointer(p: Path) -> str | None: ...      # text file, ignore *.tmp
def _point(name: str, target: str) -> None: ...    # same tmp+os.replace dance as train.py

def _weighted_ppl(results: dict) -> float | None:
    ppl = results.get("base", {}).get("perplexity", {})
    if not isinstance(ppl, dict) or "error" in ppl:
        return None
    return ppl.get("weighted")            # confirm exact key against one real report

def gate_once(preset: str, device: str, probe_n: int) -> dict:
    cand = _read_pointer(CKPT_DIR / "latest_candidate")   # debounce: newest only
    incumbent = _read_pointer(CKPT_DIR / "latest")
    if cand is None or cand == incumbent:
        return {"verdict": "noop"}
    results = run_harness(preset=preset, base_ckpt=str(CKPT_DIR / cand),
                          device=device, probe_n=probe_n, skip_needle=True)
    # copy-out BEFORE anything else: run_harness's write_reports overwrites
    # reports/branch_eval_results_real.json (footgun #4 in the eval memory note)
    out_dir = Path("reports/promotions") / cand
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(results, indent=2))
    wp = _weighted_ppl(results)
    base = json.loads(BASELINE.read_text()) if BASELINE.exists() else None
    tol = float(os.environ.get("AVA_PROMOTE_PPL_TOL", "0.02"))
    if wp is None:
        verdict, reason = "hold", "harness error or no ppl"
    elif base is None or wp <= base["weighted_ppl"] * (1 + tol):
        verdict, reason = "promote", f"wp={wp} vs base={base}"
    else:
        verdict, reason = "hold", f"regression wp={wp} > {base['weighted_ppl']}*(1+{tol})"
    if verdict == "promote":
        _point("latest", cand)
        BASELINE.write_text(json.dumps({"ckpt": cand, "weighted_ppl": wp}))
    with LOG.open("a") as f:
        f.write(json.dumps({"ts": time.time(), "candidate": cand, "verdict": verdict,
                            "reason": reason, "weighted_ppl": wp}) + "\n")
    return {"verdict": verdict, "candidate": cand, "weighted_ppl": wp}
```

CLI: `--preset mini --device cpu --once | --watch --interval 300`.

### 2.4 Cadence and GPU contention (the design constraint that matters)

- Mini harness measured ~7 min on the 4080 **GPU** (memory note, 2026-07-21). Checkpoints
  currently land every 8 steps (`configs/mini.yaml:67`) — far faster than any eval.
- Therefore the promoter must **debounce**: always gate the pointer's current value, never a
  queue. Intermediate candidates are skipped by design.
- Run eval with `--device cpu --skip-needle` and reduced `--probe-n` so it never steals VRAM
  from a live run (probes are 0/200 anyway; ppl bins are the signal). Accept the longer wall
  time; promotion latency is minutes, not 5 seconds — that is the point of a gate.
- Alternative accepted-scope cut: gate only `stable_p{phase}.pt` and `*_final.pt`
  (train.py:685) and leave step ckpts on `latest_candidate` forever. Cheaper, still kills the
  "regressed final goes live" failure mode.

### 2.5 Compose wiring (post-freeze)

New optional service in `docker-compose.yml` (profile `gate`, trainer image, volumes
`ava_ckpt:/ckpt` + `ava_state:/state` like lines 133-136), command
`python scripts/promote_ckpt.py --watch --preset mini --device cpu`, plus
`AVA_GATED_PROMOTION: "1"` added to the trainer service env. Phase 1 can skip the service
entirely and run one-shot after the run ends.

### 2.6 Eval-data provenance preconditions (from the 2026-07-21 eval session)

1. Frozen tokenizer: copy `ava_state` volume `/state/tokenizer.json` to
   `data/mini/tokenizer/ava_bpe_32k.json`; verify `vocab==32000`. Never let
   `build_eval_data.py` retrain one.
2. Heldout bins must be built with `--preset mini --target-bytes 5000000` (p4/p5 need >4096
   contiguous tokens if they are to count).
3. Ppl numbers are only comparable WITHIN one bin build — `promoted_baseline.json` must
   therefore also record a bin-build id (mtime or hash of the bins dir); on bin rebuild,
   reset the baseline on the next promote instead of comparing across builds.

## 3. Test plan

New file `apps/ava-factory/tests/test_promote_ckpt.py` (conventions per existing
`tests/conftest.py`, style of `test_codeact_eg_gate.py`). All tests monkeypatch
`promote_ckpt.run_harness` with canned result dicts and use `tmp_path` as CKPT_DIR — no
torch, no model loads.

1. promote path: better/equal ppl -> `latest` points at candidate, baseline written,
   promotions.jsonl has one `promote` row.
2. hold path: ppl worse than tol -> `latest` unchanged, `hold` row with reason.
3. error path: harness raises / returns error dict -> hold, `latest` unchanged (the
   regression that motivated this design).
4. first promotion: no baseline file -> promotes and records baseline.
5. noop: candidate == incumbent -> no harness call (assert monkeypatched fn not called).
6. pointer mechanics: written pointer is a bare filename text file, no `.tmp` left behind
   (matches `serve_engine.py:12-15` contract).
7. report copy-out exists under `reports/promotions/<cand>/` before/independent of verdict.
8. train.py flag: with `AVA_GATED_PROMOTION=1`, `_point_latest_at` writes
   `latest_candidate`; unset writes `latest` (byte-identical behavior to today).

Gate to run (RAM protocol first, >=900MB): factory suite from `apps/ava-factory` root with
`AVA_FACTORY_ROOT` set (without it: 36 false failures — test-board memory note). The suite
was ~431 tests as of the 2026-07-22 review and needs the factory env; if the host venv
can't run it, run inside the trainer image once training has ended (docker is allowed then).

## 4. Rollout order (the hour training ends)

1. Land `scripts/promote_ckpt.py` + tests; run factory suite green.
2. Land the `_point_latest_at` diff (still default-off). Suite green again.
3. One-shot gate the run's `*_final.pt` manually; inspect `promotions.jsonl`.
4. Set `AVA_GATED_PROMOTION=1` + promoter service for the NEXT run's boot
   (mini.yaml comment pattern: config changes apply on next container boot).
