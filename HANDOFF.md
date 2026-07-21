# HANDOFF — pick up and execute this session's work

**For any assistant (or the operator) resuming Dottie work. Start here.**

---

## 📌 Session continuation — 2026-07-20 23:50 CDT (autonomous /loop run)

**All work below is committed to local `main` (HEAD `12000d3`), test-verified, and additive to
the git-B0 divergence — nothing pushed.** A long autonomous review+execute loop ran while the
operator was away. What it did, and what is now YOURS to decide:

### Shipped + verified this session (13 commits, `3b77263`…`12000d3`)
- **Curriculum expansion** (the operator's `/auto-mode` ask — scout-cli, compression, DBs, ZK
  math): wired the existing `compression`/`compress_trace`/`db_trace` generators + added two new
  ones — `scout_cli` (using+building the agent CLI, grounded in the real contract) and `zk_math`
  (Schnorr/Fiat-Shamir/Pedersen/Merkle/Shamir, every transcript computed+re-verified).
  `9006865`,`3e03b44`,`8415a6b`. Every phase still sums to 1.0; **501 factory tests green.**
- **SPEC build-priorities #1–#4 closed.** #4 monitor "not_running" fix (`b378bc3`); #3 per-seed
  factory trainer **verified end-to-end on real torch** (`ca9f2f1`,`82fe0d9`); #2 measured
  substantially-done from the ledger (100% param-declaration compliance — `e6d774f`).
- **3 real correctness bugs fixed in packages** (found by review, each with tests):
  `b5c4708` graphify — internal repo path **leaked into the public graph** (rst/qmd/yaml);
  `9e87451` graphify — **dangling ecosystem edges** for every markdown doc (file:/doc: drift);
  `12000d3` harness — **`auc_trapezoid` inflated AUC on ties** (a constant classifier scored 1.0).
  Suites green: graphify **68**, harness **32/11 skip**.

### ⚠ The two decisions that are YOURS (do NOT let a future autonomous tick ship these)
- **Items 10 + 11 are COUPLED — decide together** (TODOS item 11, `76d7aaa`). The paired-seed
  eval gate (item 11, the natural SPEC-#3 completion) lowers the promotion bar ~7×; with the
  capacity gate (item 10) OFF, a capacity-*deleting* swap would then promote and re-contaminate
  the baseline. Paired significance is a net win ONLY alongside item 10. Both are operator calls
  (`evaluate.py:158`). I filed+specced them but deliberately did not ship.
- **Item 9 (NEW) — deploy the new curriculum to the running collectors** (`43bced2`). Committed
  but NOT live: collectors run the baked `ava/cpu:latest` (grep-confirmed 0 of the 3 new
  sources). Needs a local image rebuild in a **memory-ample window** (a `docker build` at
  <~2 GB free risks the VM). ⚠ NUMBERING: this NEW item 9 ≠ the OLD "item 9 WITHDRAWN" noted
  further down — that referred to a since-superseded item.

### Nothing else autonomous remains high-value
The memory-safe review surface is largely exhausted (≈11 functions verified correct across
factory/graphify/ava-skills/harness/scout-cli in addition to the 3 fixes). Remaining work is
git reconcile (#0), the coupled gates (10+11), and the memory-gated deploy (#9) — all yours.

---

The living source of truth is [`TODOS.md`](./TODOS.md) — read its **"YOUR DECISION QUEUE"**
section (search that header) and the **§5.3.R98–R100** entries at the top of the R-log. This
file is just the entry point; `TODOS.md` has the detail and stays current.

## Execute the queue TOP-DOWN — each item is a precondition for the ones below it

1. **Item 00 — reconcile git FIRST.** Local `main` is ahead of `origin/main` (unpushed
   session work) and behind by 2 (a parallel session's ruff reformat that **pruned `typing`
   imports this session's new code still uses**). A naive merge → `NameError: Dict is not
   defined` at import. **Verified procedure (§5.3.R99):**
   ```bash
   git merge origin/main            # resolve conflicts as "keep my logic, take their formatting"
   python -m ruff check --fix ; python -m ruff format   # normalises both sides; removes the NameError
   # then run the suites (see Environment) — a green suite proves the reconciliation held
   ```
2. **Item 0 / 5 — RE-SEED before restarting the daemon**, or the loop rejects every candidate
   against an unreachable baseline (the live baseline is a measured regression, §5.3.R93):
   ```bash
   python -m dottie.research calibrate-baseline --overwrite   # installs ≈5.737, ~6 min
   ```
3. **Item 0 — restart** (only after re-seed):
   ```powershell
   wsl --shutdown ; .\scripts\restart_research.ps1
   ```
4. **Items 1–8** unblock from there, in order. **Item 9 is WITHDRAWN** (was a false alarm —
   `apps/dottie` is green once `AVA_FACTORY_ROOT` is set).

## Environment

Tests **and** the trainer need:
```
AVA_FACTORY_ROOT=C:\Users\jcdav\workspace\ava-agi-factory-v6-4
```
The daemon sets it from the gitignored `apps/dottie/research_orchestration/research_env.local.ps1`.
Without it, `apps/dottie` reports ~36 failures that look like a broken repo and are not
(§5.3.R87). Run each suite from its own root; `apps/dottie` uses `apps/dottie/.venv`.

## Discipline (enforced conventions — TODOS ops §9.3–9.6)

- **`git fetch` before your FIRST commit** — parallel sessions push here (this is exactly how
  the divergence above happened).
- **`python scripts/check_todos_timestamps.py`** before committing any `TODOS.md` edit — it
  rejects fabricated clock times.
- **Read [`scripts/README.md`](./scripts/README.md)** before writing a new script — the
  operational tooling (restart/recovery, run-log reader, mutation audit, and the per-promotion
  `ab_nano.py` verifier) is indexed there.
- Never write a clock time that did not come from `date` or `git log` in the same tick.

## Status note

This file and `TODOS.md` are **local-only until item 00 is done** — `origin/main` does not yet
contain this session's work. After the git reconciliation pushes, this handoff becomes visible
to anyone with the repo. Until then, "pick up" means on this machine.
