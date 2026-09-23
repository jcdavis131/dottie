# Reward Spec — "Best Pair Programming Assistant"

**Module:** `pipeline/pair_rewards.py` (stdlib-only) · **Tests:** `apps/ava-factory/tests/test_pair_rewards.py` (25 passing)

## The definition

A great pair programmer is not the model that writes the most code — it is the one
whose contributions **pass the task's tests, break nothing, get accepted by the human,
arrive fast, and are high quality**. Each of those is independently measured.

## The formula

```
R = 1.00 · R_task_ok
  + 0.25 · R_accept
  + 0.15 · R_time
  + 0.15 · R_quality
  + 0.10 · R_tok
```

| Component | Range | Measured from |
|---|---|---|
| `R_task_ok` | 0..1 (graded) | Task's own tests; **zeroed if any pre-existing test regresses** (multiplicative gate) |
| `R_accept` | -1..1 | User signal: accept / edit / reject / revert / kept / none |
| `R_time` | -1..1 | Wall-clock vs measured task-family baseline median |
| `R_quality` | -1..1 | Independent verifier score (0–10), centered on the 8.0 gate |
| `R_tok` | -1..0 | Difficulty-scaled token penalty (from codeact `r_len`) |

## Why each component

- **R_task_ok** — the ground truth. Graded (0.7 = 70% of tests) so partial progress trains.
- **No-regression gate** — the most important anti-hack: multiplicative, not additive. A
  "fix" that breaks the suite gets zero task credit. You cannot trade a broken codebase
  for a passing demo.
- **R_accept** — the human is the customer. Explicit UI signals preferred; implicit
  (`kept` = code still present after session, `revert` = user undid it) as fallback.
  Silence is neutral (0) — never punish a user for not rating.
- **R_time** — speed matters to a human waiting. Gated on success: fast failure is not
  a virtue. Requires a real baseline; missing baseline → neutral.
- **R_quality** — tiebreaker among correct solutions. Computed by the independent
  verifier pipeline (NORTH_STAR ≥ 8.0), never by the policy grading its own homework.
- **R_tok** — token efficiency, difficulty-scaled: easy families snap to terse, hard
  families get budget for deep derivations. Bounded so it can never overturn the task term.

## Anti-reward-hacking rules (enforced in code, tested)

1. **Accepted-but-broken earns nothing** — positive accept credit requires task success.
   (Politeness is not quality.)
2. **Rejection always counts** — a reject/revert is informative even when tests passed.
3. **Edit-discount** — an "accept" where the user rewrote 50% of the lines scores 0.5.
   If they rewrote it all, it wasn't accepted.
4. **Task dominance is structural** — `grpo_collect` ranks pref pairs by the tuple
   `(task_ok, total)`, not by total alone, so a correct solution always outranks any
   wrong one regardless of weights. (Arithmetic alone can't guarantee this, because
   wrong solutions can earn positive secondary terms — hence the tuple key.)
5. **No self-grading** — verifier score comes from the separate verifier pipeline;
   baselines come from measured session history, never from the policy's estimates.
6. **Retuning guard** — keep `w_accept + w_time + w_quality + w_tok < w_task`
   or the dominance story weakens.

## How it feeds grpo_collect.py

`to_telemetry(trace, extra={...})` emits a row `grpo_collect` already understands:

```json
{"rl_return": 0.83, "verdict": "pass", "task_ok": 1,
 "reward_components": {"r_task": 1.0, "r_accept": 0.5, "r_time": 0.5, "r_quality": 0.5, "r_tok": -0.19, "total": 0.83},
 "user_signal": "edit", "regression": false, "trace_id": "...", "prompt": "..."}
```

`grpo_collect` reads `rl_return` (falling back through `reward`/`score`), groups by
prompt, and forms chosen/rejected pairs from max/min return with its margin filter.
**Recommended:** sort by `rank_key(trace)` = `(task_ok, total)` when selecting
chosen vs rejected, so the task tier dominates. The `reward_components` dict is
carried through so MANIFESTs and reports stay auditable — every number traceable
to a measured input.

## What still needs instrumentation (not this lane)

The reward is defined and computable; the missing inputs are capture, not math:
explicit accept/reject UI in the pair-programming flow, session wall-clock and
baseline medians per task family, and pre/post full-suite test results per episode.
