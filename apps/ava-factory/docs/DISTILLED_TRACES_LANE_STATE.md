# Distilled reasoning traces → nano GRPO — measured state

> Lane: the FREE half of dottie on the coordination board.
> Scout holds `dottie / nano 1k + tech debt` (`scout/dottie-dottie-nano-1k`); this is not that.
> Nothing here was modified. `apps/ava-factory/dottie/**` and `apps/ava-factory/configs/**`
> are FROZEN and were read only.

## Bottom line

**Not actionable end-to-end today, and the freeze is not why.**

Two things are missing, and they are in different places:

1. **No nano checkpoint on disk.** `find apps/ava-factory -name "*.pt"` returns **0**.
   `rl_smoke_update.py` cannot start. This falls inside **Scout's** lane, not this one.
2. **The banked traces carry no token-level data.** GRPO needs `actions` (token ids) and
   `old_logp`. The traces have neither. This is **not** Scout's and **not** frozen — it is
   the actual content of this lane.

## What exists

**GRPO is implemented, not stubbed.** `apps/ava-factory/dottie/rl/grpo_torch.py`,
`TorchGRPOStep` — real `zero_grad` / `loss.backward()` / `clip_grad_norm_` /
`optimizer.step()`, two-layer clipped surrogate, entropy thermostat, `state_dict` round-trip.
The one refusal stub, `GRPOOptimizerStep.step()` in `grpo.py`, is deliberate and documented
as a signpost to the torch path — `rl/__init__.py` calls it a "legacy refusal stub".

**Its input contract is plain tensors, not a trace object:**

```
TorchGRPOStep.step(policy_inputs, actions, old_logp, advantages, mask=None) -> GRPOStepStats
    actions / old_logp : [B] or [B,T]
    advantages         : [B], one per rollout, already group-normalised
    mask               : [B,T], 1 = real token
```

**The trace→tensor conversion ALREADY lives outside the freeze.**
`apps/ava-factory/scripts/rl_smoke_update.py::build_grpo_batch` right-pads a causal-LM
batch and is the only production caller of `.step()`. Verified: that function is in
`scripts/`, not in `dottie/rl/`.

**60 traces on disk.** `apps/dottie/data/traces/traces.jsonl`, 97,961 bytes, 60 records
(40 `ava` / 20 `ollama`, all `plumbing_only: false`). Written by
`apps/dottie/dottie/engine.py::_append_trace`, read back by `iter_traces`.

Record schema, parsed from all 60:

```
top level : backend final n_steps plumbing_only prompt reached_final reward_components
            schema_version steps task_id terminated ts verified_task wall_s
steps[]   : code error ok stdout tool_calls value wall_ms
```

`reward_components` carries real measured values, e.g.
`{"r_exec": 1.0, "r_codeuse": 0.0, "redundant_calls": 0, "r_task": 1.0, "rl_return": 1.2}`.

## What does NOT exist

**No checkpoint.** Zero `.pt` files anywhere under `apps/ava-factory`.
`apps/ava-factory/runs/cpu_pilot/` holds only `MANIFEST.json`, `reports/`, `tokenizer/`.
`_resolve_ckpt` therefore raises `FileNotFoundError: no pilot checkpoint under {run_dir}`.

**The traces feed nothing.** `rl_smoke_update.py` references `traces.jsonl` **0 times**
(verified by grep). It regenerates rollouts live instead. The 60 banked traces are
connected to no consumer.

**No token-level fields in any trace.** Scanning all 60 records:

```
'logp'      0 hits        'token_ids'  0 hits        'old_logp'  0 hits
'logprob'   0 hits        'gen_ids'    0 hits        'action'    0 hits
```

They hold text (`prompt`, `final`, per-step `code`/`stdout`/`value`) and a scalar
`rl_return`. GRPO needs token ids and per-token old log-probs. **A scalar return per
trajectory cannot be turned into `old_logp` after the fact** — the log-prob had to be
recorded by the policy that generated the tokens, and that policy is gone.

## The freeze is not the blocker

Frozen: `apps/ava-factory/dottie/**`, `apps/ava-factory/configs/**`.

That prevents editing the optimizer step, the advantage math, the thermostat, the reward
functions, and RL hyperparameter defaults.

It does **not** touch a single file the trace→GRPO data path would need.
`apps/ava-factory/scripts/**` is editable and is where `build_grpo_batch` already lives.
`apps/dottie/**` (the trace writer) is editable. `apps/ava-factory/docs/**` is editable.

## What could be done here without touching frozen paths or Scout's area

Recording the option, not taking it — the checkpoint half is Scout's and this half needs a
decision that is not mine:

- **Extend the trace writer to record token ids and per-token log-probs at generation
  time.** `apps/dottie/dottie/engine.py::_append_trace` is editable. This is the only way
  the banked-trace path becomes real, and it only helps traces recorded *after* the change
  — the existing 60 are unrecoverable for this purpose.
- **Or accept that `rl_smoke_update.py`'s live-rollout path is the design**, and treat
  `traces.jsonl` as an observability artifact rather than an RL input. That is a
  one-line decision, and it makes "distilled traces → nano GRPO" a no-op by definition.

Which of those is right is a design call for the repo owner. Both are cheap to state and
neither should be guessed at by a passing agent.

## What I could not verify

- The 7 `bundles/*` referenced elsewhere in the estate are not on this box.
- I did not run anything. No training, no `rl_smoke_update.py` (it cannot start without a
  checkpoint), no tests.
- Whether Scout's nano-1k run will produce the missing `.pt` — that is their lane and
  their timeline.

## Method

29 agents: 4 independent readers over disjoint areas, then one adversarial verifier per
claim instructed to REFUTE and to default to REFUTED when the cited quote was not in the
cited file. **16 CONFIRMED, 8 REFUTED, 0 unverifiable** — the 8 refutations are why the
confirmed set is worth reading.

Four load-bearing claims were then re-verified by hand, independently of the agents:
the 60-record trace count and its 0-hit token-field scan, the 0 `.pt` files, the 0
`traces.jsonl` references in `rl_smoke_update.py`, and `build_grpo_batch`'s location
outside the frozen path. All four held.
