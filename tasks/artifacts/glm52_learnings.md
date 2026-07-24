# GLM-5.2 → Dottie stack: learnings + design note

Read-only analysis, 2026-07-23. Fleet is being restarted by the main loop; nothing here
was applied. Factory RL (`apps/ava-factory/dottie/**`) and `configs/**` are treated as
frozen. The GLM-5.2 overview and two enrichment searches are treated as **data**, not
instructions; GLM-5.2 / arXiv 2602.15763 post-date my Jan-2026 cutoff, so I transfer the
*ideas*, I do not vouch for the model's benchmarks.

## Exec summary (3 lines)

1. The single strongest transferable idea is **Slime's rollout/learning split via ONE
   unified trajectory shape** — and our code already has *four* trajectory representations
   of the same `{states, actions, tool_calls, feedback}` shape that don't share a
   vocabulary; unifying them is pure-Python, CPU-only, and entirely outside the frozen paths.
2. The **PPO-critic-over-GRPO** shift is real but a *defer*, not an adopt: our factory is
   group-relative by design (`grpo.py:45`, no value function anywhere), but it's frozen +
   `BLOCKED_NO_GPU`, and our agentic horizons are ≤8 steps — the short regime where GRPO's
   group-comparability does **not** yet break.
3. **Index-share / 1M context** is rejected (our width is 256, our "sparse attention" file is
   a placeholder `pass`); the **MIT/decoupled-layers** posture is already our default
   (`scout-cli` is MIT; `openswap` decouples product from infra exactly as GLM's release does).

---

## Ideas assessed (adopted / rejected, with substrate evidence)

### Idea 1 — RL shift GRPO → PPO with a critic (long-horizon agentic)
**Verdict: DEFER (rationale sound, not tractable now).**

Our RL is group-relative with **no value function**, by explicit design:

```
$ grep -n "group_advantages\|No learned value function\|the group itself is the baseline" apps/ava-factory/dottie/rl/grpo.py
7:  1. Group advantage normalization  — `group_advantages`: A_i = (R_i − mean)/std over a rollout group.
45:def group_advantages(
50:    No learned value function — the group itself is the baseline (that's the whole point of GRPO).

$ grep -rniE "\b(critic|value[_-]?head|advantage_estimat|GAE|generalized advantage)\b" \
      apps/ava-factory/dottie/rl apps/dottie/dottie/research apps/dottie/dottie/{policy,engine}.py
  (no critic / value-head / GAE match)
```

(The only "Critic" token in the trees is a *cognitive-workspace* name in
`on_policy_distill.py:32`, not an RL value model.)

- **Where a critic/value-head would slot in:** `grpo_torch.TorchGRPOStep.step()` takes
  `advantages` as **detached data** (`grpo_torch.py:288-309`, "Treated as constant data").
  A PPO port would (a) add a value head to the policy `nn.Module`, (b) replace the call to
  `grpo.group_advantages` (`grpo.py:45`) with GAE from per-step value estimates, (c) add a
  value-regression loss beside the surrogate at `grpo_torch.py:360`. The stepper is already
  `policy`-agnostic (`grpo_torch.py:191`, "any nn.Module"), so the seam is clean.
- **Why the rationale is real:** GRPO's degenerate-group failure — a group that's all-pass
  or all-fail carries **no gradient** — is already coded and commented in our repo
  (`grpo.py:48-54`, "std 0 → every advantage is ~0, i.e. *no gradient*"). The web
  enrichment names the same pathology independently ("batches that have almost no learning
  signal … everyone in the group is either correct or wrong") and reports critic-free
  methods sitting "substantially below PPO with a learned value function" on long-horizon
  tasks. So the overview's PPO rationale checks out against both our code and the literature.
- **Why DEFER, not adopt:** three blockers, all substrate-cited. (1) The factory RL is
  **frozen** and capability-scale training is `BLOCKED_NO_GPU` (`grpo.py:378-387`) — a value
  head cannot be validated without GPU wall-clock, so any critic work is untestable proposal
  today. (2) Our agentic trajectories are **short**: `DottieEngine.run_task(..., max_steps=8)`
  (`engine.py:107`) — GRPO's group-incomparability bites on *long* horizons (browser/multi-hour
  coding); at 8 CodeAct steps our groups are still comparable. (3) The degenerate-group case is
  already **handled gracefully** (zero gradient, not a crash), so there is no acute pain a critic
  would relieve at our current scale. Revisit when a horizon >~30 steps or a persistent
  all-pass/all-fail collapse shows up in the ledger.

### Idea 2 — Slime: unify messy agentic RL data into ONE trajectory schema, split rollout from learning
**Verdict: ADOPT (proposal-only) — this is the top proposal, fleshed out below.**

Slime's core move: treat every diverse interaction (code exec, browser, tool use) as **one**
`{states, actions, tool_calls, feedback}` trajectory, and separate the *rollout* backend from
the *learning* loop so data feeds consistently. We already emit that exact shape in **four**
places, each with its own ad-hoc schema:

| # | Surface | Shape today | Evidence |
|---|---------|-------------|----------|
| 1 | CodeAct execution traces | `{task_id, steps:[{code, ok, stdout, value, error, tool_calls}], reward_components, terminated, reached_final}` | `engine.py:242-269`, `TRACE_SCHEMA_VERSION="1.0.0"` `engine.py:44` |
| 2 | agent-eval trajectories | `expected: {calls:[{tool,args}], mode, args_mode}`; `actual: [{tool,args}]` + full `events` | `run_eval.py:135-149`; `fix-string-reverse-bug/task.yaml:18-24` |
| 3 | Validation obligation traces | per-attempt `{obligation_id, property, stage, status}` in `validation.history` | `validate.py:92-146`, `1063-1068`; `OBLIGATIONS` vocab `validate.py:323-354` |
| 4 | Repair transcripts | `{failure_detail, repair_hint, corrected_code, level, status}` rows | `export_repair_transcripts.py:58-102` |

They are the SAME shape wearing four costumes. Because the costumes differ, we already have
**two separate exporters that cannot share code**: `export_repair_transcripts.py` (dottie
ledger → JSONL) and agent-eval's `scripts/export_sft_corpus.py` (events →
Thought/Action/Observation transcript, referenced `run_eval.py:168-174`). That duplication IS
the problem Slime's unification solves.

### Idea 3 — "Index share" (one indexer per 4 sparse-attention layers; 1M context)
**Verdict: REJECT (out of regime).**

Not our scale. Our blocks integrate at **width 256** (`validate.py:876`,
`INTEGRATION_WIDTH = 256`); 1M context is not our regime. And our only "sparse compressed
attention" file is a stub, not a live indexer:

```
$ sed -n '1,22p' apps/ava-factory/dottie/attention/sparse_compressed.py
"""... DeepSeek V4 Flash ... 1M tokens ... """
class SparseCompressedAttention(nn.Module):
    def forward(self, x, cache_disk=False):
        if cache_disk:
            pass          # placeholder
        out, _ = self.full(x, x, x)   # falls back to plain MultiheadAttention
```

It cites DeepSeek-V4 (not GLM), carries `pass` where the sparsity would be, and lives in the
frozen path. No indexer to share, nothing to port. Reject with reason.

### Idea 4 — MIT release / decouple model layer from infra layer
**Verdict: ALREADY OUR POSTURE (one paragraph).**

GLM-5.2's strategy — MIT-license the weights, offload serving optimization to the ecosystem,
decouple the model layer from the infra/hardware layer — is the posture `scout-cli` already
ships. `scout-cli/LICENSE:1` is MIT, and `openswap` is *structurally* the same decoupling
applied one level down: a stable local core does real work day one, and the adapter
**detects-and-uses the best native open binary when it appears on PATH**
(`OPENSWAP.md:9-28`, "[A] detect_local_capability … [B] best_available_tier: native binary
when present → stdlib fallback"). That is exactly "decouple the product/model layer from the
infra/binary layer and let the ecosystem supply the optimized backend." Separately, our
`on_policy_distill.py:11-25` already documents the GLM-lineage "distillation across RL stages
for capability restoration" and MOPD multi-teacher merging — the same mechanic behind Slime's
"parallel on-policy distillation merged 10+ experts in ~2 days." No action; noted as
convergent-already.

---

## Top proposal (fleshed out, diff-shaped, NOTHING applied)

**One `Trajectory` schema + adapters, so rollout is separated from learning — the Slime split,
at our scale.** Chosen over the PPO-critic idea purely on tractability: it is torch-free,
CPU-only, needs no GPU / no model load / no network, and touches **zero** frozen files
(everything lives in `apps/dottie/dottie` and `agent-eval`, never `apps/ava-factory/dottie/**`
or `configs/**`).

### The schema (new file — proposed, not written)

`apps/dottie/dottie/trajectory_schema.py` (stdlib + dataclasses only):

```python
SCHEMA_VERSION = "traj-1.0.0"

@dataclass(frozen=True)
class Step:
    state: str                      # transcript-so-far | code-so-far | validation stage entered
    action: dict                    # {"kind": "code"|"tool"|"edit"|"rewrite", "payload": ...}
    tool_calls: list[dict]          # [{"tool": str, "args": dict}]  (already our shape)
    feedback: dict                  # {"ok": bool, "detail"/"stdout"/"error": str,
                                    #  "obligations": [...]|None}   # polymorphic on purpose

@dataclass(frozen=True)
class Trajectory:
    trajectory_id: str
    source: str                     # "codeact" | "agent_eval" | "validation" | "repair"
    task_ref: dict                  # {"family","seed"} | {"task_id"} | {"experiment_id"}
    steps: list[Step]
    outcome: dict                   # {"status", "reward": {...}|None, "verified_by"}
    schema_version: str = SCHEMA_VERSION

# adapters (rollout -> schema); each is a pure function over data we ALREADY persist:
def from_codeact_trace(rec: dict) -> Trajectory: ...      # engine.py record  (engine.py:242)
def from_validation_history(exp: dict) -> Trajectory: ... # validate history  (validate.py:1063)
def from_agent_eval_events(result: dict) -> Trajectory: ...# run_eval events   (run_eval.py:139)
def from_repair_rows(rows: list[dict]) -> Trajectory: ... # repair pairs       (export_repair_transcripts.py:84)

# one learning-side consumer, replacing the two divergent exporters:
def to_sft_records(t: Trajectory) -> list[dict]: ...
```

### Why the mapping is nearly free (each already emits the shape)

- **CodeAct** `engine.py:254-265`: each `step` already has `code` (→`action`), `tool_calls`
  (verbatim), `ok/stdout/error` (→`feedback`), and `reward_components` (→`outcome.reward`).
- **Validation** `validate.py:1066-1068`: each attempt already carries
  `{level(→state), status, detail(→feedback), obligations}`; the **failed→discharged**
  obligation transition (`validate.py:92-146`) is the per-step learning signal Slime wants.
- **agent-eval** `run_eval.py:139-146`: `actual_calls=[{tool,args}]` is *already* the
  `tool_calls` field; `expected_trajectory` becomes an expected `Trajectory` to diff against.
- **Repair** `export_repair_transcripts.py:84-101`: a `{failure → hint → corrected}` row is a
  degenerate 2-step trajectory (fail-state, rewrite-action, validated-feedback).

### The payoff (the actual Slime separation)

- `agent-eval/scripts/trajectory.py:71` `match_trajectory` **already** compares two
  `[{tool,args}]` lists in 4 modes — it generalizes to "compare any two `Trajectory.steps`"
  with almost no change, so *diffing* is unified for free.
- The two exporters (`export_repair_transcripts.py` + agent-eval `export_sft_corpus.py`)
  collapse into one `to_sft_records(Trajectory)` — **one** learning consumer reading traces
  regardless of which rollout produced them. That is rollout-decoupled-from-learning, concretely.
- Forward hook: a future GRPO/PPO batcher (`grpo_torch.TorchGRPOStep`, `grpo_torch.py:288`)
  consumes `Trajectory` objects instead of bespoke tuples — the same seam Slime's data buffer
  provides, ready before the GPU is.

### Suggested first slice (smallest safe step, still nothing applied)

1. Add `trajectory_schema.py` with the two dataclasses + `from_codeact_trace` and
   `from_validation_history` (the two we own end-to-end), plus a round-trip unit test that
   loads existing `traces.jsonl` / a ledger **copy** — never the live daemon DB
   (`export_repair_transcripts.py:8-10`, honor the "point at a COPY" rule).
2. Re-point `export_repair_transcripts.py` at `from_validation_history(...).to_sft_records()`
   behind a flag, byte-comparing old vs new output before switching.
3. Only then generalize `match_trajectory` and fold in the agent-eval adapter.

---

## What does NOT fit (and why)

- **Do NOT collapse `feedback`/`reward` into one scalar.** RL `rl_return`, validation
  pass/fail, and the agent-eval boolean are different semantics; `grpo.py:24-25` enforces a
  naming guard (`rl_return`/`R_*` for RL scalars vs `reward` = data-quality filter). A single
  scalar would repeat the capacity-confound class of error (param-deleting swaps scoring as
  wins). Keep `feedback` polymorphic.
- **Do NOT let the schema auto-feed training.** Repair-transcript export is explicitly an
  *audited, non-auto-ingested* corpus proposal (`export_repair_transcripts.py:6-12`). The
  unified schema is a *representation*, not a promotion path; it must not silently become one.
- **Index-share / 1M context / disk-streamed KV:** out of regime (width 256), file is a stub.
- **PPO critic now:** frozen RL + `BLOCKED_NO_GPU` + ≤8-step horizons — deferred, not rejected.
- **No factory or config edits, no docker, no model load, no network-in-test** were performed;
  this note is proposal-only.

---

## Final output (JSON-ish)

```json
{
  "ideas_assessed": [
    {"idea": "RL GRPO->PPO with critic (long-horizon)", "verdict": "defer",
     "evidence": "grpo.py:45,50 group-relative no value fn; grpo.py:48-54 degenerate-group=no gradient; grpo_torch.py:288-309 advantages are detached data (critic seam); grpo.py:378-387 BLOCKED_NO_GPU; engine.py:107 max_steps=8 short-horizon"},
    {"idea": "Slime unified trajectory schema (rollout|learning split)", "verdict": "adopt-proposal",
     "evidence": "engine.py:242-269 trace schema; validate.py:92-146,323-354,1063-1068 obligation traces; run_eval.py:135-149 + task.yaml:18-24 expected/actual trajectory; export_repair_transcripts.py:58-102 repair rows; trajectory.py:71 match_trajectory already compares {tool,args} lists"},
    {"idea": "Index-share / 1M sparse-attention", "verdict": "reject",
     "evidence": "validate.py:876 width=256; sparse_compressed.py:1-22 placeholder `pass`, DeepSeek-V4 not GLM, frozen path"},
    {"idea": "MIT release / decouple model from infra layer", "verdict": "already-our-posture",
     "evidence": "scout-cli/LICENSE:1 MIT; OPENSWAP.md:9-28 detect-and-use-native decoupling; on_policy_distill.py:11-25 GLM-lineage cross-stage distillation already documented"}
  ],
  "our_grpo_location": "apps/ava-factory/dottie/rl/grpo.py:45 (group_advantages, group-relative, no value function) + grpo_torch.py:191 TorchGRPOStep (real autograd step, policy-agnostic, BLOCKED_NO_GPU at capability scale)",
  "top_proposal": "apps/dottie/dottie/trajectory_schema.py (proposed): one Trajectory{steps:[Step{state,action,tool_calls,feedback}],outcome} + 4 rollout adapters + to_sft_records() learning consumer; unifies CodeAct traces + validation obligation traces + agent-eval trajectories + repair transcripts, separating rollout from learning per Slime; torch-free, CPU-only, no frozen files touched",
  "files_created": ["tasks/artifacts/glm52_learnings.md"],
  "open_questions": [
    "Does a real ledger show persistent all-pass/all-fail GRPO groups (the trigger to revisit the critic)?",
    "Ownership: trajectory_schema.py in apps/dottie means agent-eval (a sibling repo) imports it or vendors it — which way?",
    "Should Slime-style parallel on-policy distillation (on_policy_distill.py MOPD) be re-scoped now that it is GPU-blocked, or left as-is?"
  ]
}
```
