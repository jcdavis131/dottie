# Spec 13 — CodeAct / LLM-VM: code as the model's action substrate

- **Spec ID:** 13_codeact
- **Worker tier:** 🟪 Opus — this changes what the model's *actions are* (executable code, not
  prose or JSON tool-calls) and adds a live code interpreter to the training and serving loops;
  a sandbox escape or a reward that pays for plausible-but-unexecuted code corrupts the whole climb.
- **Dependencies:**
  - `specs/12_rl_training.md` (T12R.1 verifiable returns, T12R.2 GRPO-lite discipline system,
    trace-bank recovery) — CodeAct is an **agentic mode of the spec-12 loop**, not a parallel RL system.
  - `ava/datagen/code_gen.py` (`run_sandboxed(code, steps)`, `_run_with_timeout`, `FORBIDDEN_TOKENS`)
    — the existing in-process exec precedent the sandbox extends.
  - `ava/datagen/react_tools.py` — the ReAct grounding corpus (Thought → tool call → Observation),
    whose **grounding-over-syntax** philosophy CodeAct datagen inherits.
  - `ava/datagen/base.py` (`Generator`, `make_doc`, `VALID_TASK_TYPES`), `ava/serve_engine.py`
    (`ServeEngine.generate`), `evals/run_harness.py` + anti-mock guard, `efficiency_gain.py` (EG gates).
  - Cross-repo precedent: `ava-skills` `code-bench` `exec_verify()` (subprocess exec + stdout check).
- **Consumers:** the Agentic branch specialist (spec 12 T12R.2, agentic climb), `ServeEngine`
  (code-act serving loop), `docs/DISTILLATION_INTEGRATION.md` MOPD (CodeAct traces join the
  consolidation trace pool), `ava-skills` memory-mint (CodeAct episodes are high-value memory shards).
- **Status:** **T13C.1 landed** (`ava/rl/codeact_sandbox.py` + `tests/test_codeact_sandbox.py`,
  14/14 — all five accept criteria); T13C.2–T13C.3 GPU-free and next; the RL halves
  (T13C.4–T13C.5) inherit spec 12's block on branch fine-tunes (T9.3/T9.5). Findings source:
  `docs/RL_INTEGRATION.md` (MAI-Thinking-1 agentic SWE + tool-use findings).

## What this is (the LLM-VM concept)

Today Ava's tool use is **narrated**: the model writes `Thought: … / Action: tool(x) / Observation: …`
as text (`react_tools.py`), and nothing executes. CodeAct makes the model's **action space executable
Python**: each action is a code block run in a persistent namespace — the *LLM-VM* — whose tool
functions are bound as callables, whose variables persist across turns, and whose stdout / return
values become the next observation. The model *thinks in code*: it computes, calls tools, inspects
results, and branches — by writing and running a program, not by pattern-matching a JSON schema.

```
prompt + tool bindings ──► model emits ```python … ``` (an ACTION)
                              │
                              ▼
                     CodeActSandbox.step(code)          # persistent namespace, tools bound,
                              │                          # network off, resource-capped, deterministic
                     stdout / return / traceback  ──► appended as Observation
                              │
                     model emits next action, or FINAL(answer)
```

Why this is the right substrate for Ava: composition (loops/conditionals/variables the model
already learned from the 54.6% code corpus) instead of one-shot tool JSON; verifiable outcomes
(the program either produces the checked result or it doesn't); and it is exactly the difficulty-
scaled length-penalty target from spec 12 — easy tasks should snap to a one-line program, hard
tasks earn a multi-step derivation.

**Naming guard (inherited from spec 12):** RL scalars are `rl_return` / `R_*`; `reward` stays the
data-quality filter score. CodeAct-specific components are `R_exec`, `R_codeuse`; metrics namespaced
`rl.codeact.*`. The word "sandbox" here means the CodeAct execution VM, distinct from spec 12's SEE.

## T13C.1 — CodeActSandbox (build first, GPU-free, testable today)

`ava/rl/codeact_sandbox.py`. A stepwise interpreter with a **persistent namespace across turns**
(the VM), extending `code_gen.run_sandboxed` from single-shot to multi-turn.

- `Sandbox(tools: dict[str, Callable], *, timeout_s, mem_mb, max_steps)` — tools are bound into the
  namespace; each is a plain Python callable the model may invoke.
- `.step(code) -> Observation(stdout, value, error, wall_ms)` — exec's the block in the retained
  namespace; captures stdout, the last-expression value (`repr`, truncated), and any traceback.
- **Isolation is mandatory, not best-effort:** run each step in a subprocess (like `exec_verify`),
  not in-process `exec` — `FORBIDDEN_TOKENS` in `code_gen.py` is a *datagen* convenience, not a
  security boundary. No network (spec 02 already forbids it), no filesystem writes outside a temp
  scratch dir, wall-clock + memory caps, and a hard step cap. Determinism: seed `random`, freeze
  `time`/`date` via injected tools (reuse `react_tools`' `get_clock`), forbid nondeterministic
  builtins so a trajectory replays byte-identically.
- Tool-call accounting: the sandbox records which bound tools were called, with args, per step —
  the substrate for `R_codeuse` (T13C.4) and for the parallel-vs-redundant signal.

*accept:* (a) a multi-step program that sets `x` in step 1 and reads it in step 3 works (namespace
persists); (b) an infinite loop / fork bomb / `while True` is killed at the wall/step cap and the
episode continues with an error Observation (no hang, no host impact); (c) an attempt to open a
socket or write outside scratch fails and is reported, not silently allowed — verified by test;
(d) the same (seed, tool set, program) replays byte-identical Observations; (e) anti-mock guard
passes (no hardcoded Observations).

**✅ Landed 2026-07-17** — `ava/rl/codeact_sandbox.py` (`Sandbox` / `Observation`) +
`tests/test_codeact_sandbox.py` (14/14). Design note: the "persistent namespace" + "subprocess
isolation" tension is resolved by a **single long-lived worker subprocess** holding the namespace
(the VM), driven over a one-line-JSON pipe; the parent enforces the per-step wall cap by killing
the worker's process group (`setsid` + `killpg`) on overrun. POSIX resource caps
(`RLIMIT_AS`/`CPU`/`NPROC`/`FSIZE`) + a guarded `open` (writes only under scratch) + blocked
`socket`/`os.fork`/`os.system` give reasonable training-time isolation (documented as *not* a
hostile-code jail — true jailing needs containers/seccomp, tracked as a follow-up). Tools bindable
by importable `module:qualname` or by `tool_sources`; an injected frozen `get_clock()` + fixed
`PYTHONHASHSEED` make replays byte-identical. Every Observation field is measured — no fabrication.

## T13C.2 — CodeAct datagen (GPU-free)

`ava/datagen/codeact.py`, a `Generator` (spec `base.py`) emitting **executable** trajectories whose
answers are computed in Python from the same values rendered into the prompt (the `workflow_jobbench`
rule — never templated as literal text). Inherits `react_tools.py`'s **grounding-over-syntax** bias:
a large fraction of trajectories must teach *the program's output contradicted the assumption — say so
and re-plan*, not *I wrote code, therefore I succeeded*. `task_type` ∈ existing `VALID_TASK_TYPES`
(`deliberate` for compute/tool, `temporal` for multi-step workflows). Families:
- `codeact_compute`: answer must come from a run expression, not the model's mental arithmetic.
- `codeact_tool`: a bound tool returns a value the program must actually consume (mismatch = fail).
- `codeact_multistep`: plan → run → inspect Observation → run next with the *observed* value.
- `codeact_recover`: the first program errors / returns the wrong shape; the trajectory must debug it.

*accept:* 100% of emitted trajectories re-execute under T13C.1 to the labeled answer; no answer
leakage (prompt never contains the answer string — automated check); grounding-family share ≥ a
configured floor; deterministic byte-identical regeneration per seed; `validate_doc` passes.

**✅ Landed 2026-07-17** — `ava/datagen/codeact.py` (`CodeActGenerator`, `iter_trajectories`) +
`tests/test_codeact_datagen.py` (10/10). Four families (compute / tool / multistep / recover),
grounding-share scheduler enforcing the floor. Equivalence is airtight because emitted code carries
**no randomness and no wall-clock** (the private `rng` only picks parameters; time is the sandbox's
frozen `get_clock()`), so the in-process answer equals the subprocess sandbox's — the test proves it
by re-running every trajectory through the real T13C.1 `Sandbox`. Answers are computed by running
the code (never templated); the recover family's first block genuinely raises (KeyError) and the
Observation shows the failure. `codeact_recover`/`codeact_tool_grounding` are the grounding families.

## T13C.3 — CodeAct eval in the harness (GPU-free plumbing, real at eval time)

A `@register_eval` in `evals/` (spec 06): run the model in CodeAct mode over a frozen held-out set
(T13C.2 snapshot), execute each trajectory in the T13C.1 sandbox, score `exec-verified success rate`.
Follows the anti-mock contract — mock mode = seed-varying plumbing; real mode = live model or the
honest-failure record (never a fabricated success rate). Feeds `test_no_mock.py`.

*accept:* mock/real split honored; success rate is computed from actual sandbox execution, not a
constant; two seeds differ in mock mode; a deliberately-broken tool binding drops the score
measurably (the eval must be *sensitive*, not decorative).

**✅ Landed 2026-07-17 (scoring engine + honest real path)** — `evals/codeact_eval.py` +
`tests/test_codeact_eval.py`. `score_emission()` runs emitted blocks through the real T13C.1
Sandbox and checks the final value == gold answer (the live engine). `simulate_policy_eval()` is a
clearly-labeled synthetic-policy plumbing check (seed-varying, sensitive to a broken tool binding —
verified). `run_codeact_eval()` (real model) **fails honestly** until the CodeAct decode loop
(T13C.5) exists — never fabricates a rate. run_harness wiring lands with T13C.5's real path.

## T13C.4 — CodeAct return terms (extends spec 12 T12R.1/T12R.2)

CodeAct is a rollout mode of the spec-12 GRPO loop, reusing its discipline system unchanged
(entropy thermostat, outer ratio clip, trace-bank recovery). The `rl_return` gains code terms:

```
rl_return += w_exec·R_exec + w_codeuse·R_codeuse
R_exec     : fraction of emitted code blocks that executed without an uncaught traceback
             (penalizes "narrated"/hallucinated code that doesn't run)
R_codeuse  : + reward independent tool calls that advance the task (parallelizable work),
             − penalty for redundant/duplicated calls (identical tool+args in consecutive steps)
             — the MAI tool-use finding; the redundancy signal already exists in scout-cli's
             RFT `reward_components.redundant_steps`, mirrored here over sandbox tool-call logs.
```

`R_task` (final answer verified by the sandbox) and the **difficulty-scaled length penalty** carry
over from spec 12 unchanged — for CodeAct, "length" is total executed-code + observation tokens, so
easy tasks are pushed toward a one-line program and hard tasks earn multi-step budget. `R_exec` must
be *secondary* to `R_task`: running trivially-correct code that doesn't solve the task must score
below a terse correct solution (guard against reward-hacking by emitting many tiny valid statements).

*accept (nano→mini):* an undisciplined ablation (no length penalty) shows trajectory bloat while
the disciplined run holds median code length within band; a policy that emits non-executing code
is measurably penalized vs one that runs; redundant-call rate does not rise across the climb;
`R_exec`-hacking (many trivial statements, wrong answer) scores below a correct terse solution.

**◑ Reward functions + GRPO discipline mechanics landed 2026-07-17; the torch climb stays gated.**
`ava/rl/codeact_rewards.py` (`r_exec`, `r_codeuse` incl. `redundant_calls`, `r_len`,
`codeact_return`) + `tests/test_codeact_rewards.py` — pure, GPU-free, tested against real sandbox
execution logs (a clean trajectory scores `r_exec`=1.0; the recover family < 1.0;
consecutive-duplicate tool calls lower `r_codeuse`; `r_len` is difficulty-scaled; the blend keeps
`w_task` dominant so R_exec-hacking scores below a correct terse solution).

The **spec-12 T12R.2 discipline system** it plugs into now exists GPU-free in `ava/rl/grpo.py`
(+ `tests/test_grpo.py`, 29/29): group-relative advantages `(R−mean)/std`; the entropy thermostat
as an integral controller `k ← clamp(k+κ·(H_target−H),0,k_max)` relaxing only the upper clip bound
`(1+ε)·(1+k)` (bounds are symmetric log-ratio inverses at k=0); the outer ratio-clip circuit
breaker `|r−1|≤r_outer` applied before/regardless of the standard clip's unclipped zones; and the
trace bank with prompt-deduped, per-prompt-capped, **uniform** recovery sampling (the source's
ablation winner). A synthetic control-systems plant (`simulate_entropy_control`, clearly labeled
NOT a training measurement) demonstrates accept-criterion (a): the disciplined run holds the entropy
band ≥10× longer than the κ=0 ablation, which collapses to the floor.

**Amended 2026-07-17 (later the same day): the torch optimizer step now EXISTS** —
`ava/rl/grpo_torch.py` (`TorchGRPOStep`, `clipped_surrogate_torch`,
`importance_weighted_entropy_torch`; 10 tests): exact parity vs the pure-math surrogate
(16×7×3×3 grid, ≤1e-6, identical clip flags, all four clip zones), thermostat/outer-clip wiring,
a measured synthetic-bandit learning demo (mean rl_return 0.28→1.0 over 300 real CPU steps), the
spec-12 criterion-b spike test, a true-float32-exp-overflow NaN-survival regression (log-ratio
capped before exp — adversarial-verifier HIGH finding, fixed), and checkpoint round-trip. A REAL
GRPO update on the REAL smoke-scale agentic branch checkpoint ran end-to-end
(`scripts/rl_smoke_update.py`; evidence in `runs/cpu_pilot/MANIFEST.json`). The legacy
`GRPOOptimizerStep` stub now refers callers to `TorchGRPOStep` and still refuses. **Gated now:
only the capability-scale climb** (mini+ checkpoints, GPU wall-clock).

## T13C.5 — Consolidation & serving

- **Consolidation:** verified CodeAct trajectories join the MOPD trace pool
  (`docs/DISTILLATION_INTEGRATION.md`) so the unified model retains code-as-action after merge;
  `safety_blackmail` 0/180 must hold post-consolidation (a code interpreter is an attack surface —
  the Critic-scoped safety set must include "refuse to run this" cases).
- **Serving:** `ServeEngine.generate` gains a code-act loop (emit code → T13C.1 sandbox → observe →
  continue → FINAL), reusing the thought/answer separation the Mem0-style memory pattern already
  wants (`docs/RL_INTEGRATION.md` second-pass): only the FINAL answer reaches the user; the
  code+observation trace is captured for debugging and for memory-mint ingestion.

*accept:* post-MOPD CodeAct eval (T13C.3) within noise of the pre-merge specialist; safety set holds;
serving loop executes a multi-step task end-to-end in the sandbox and returns only the sanitized FINAL.

**◑ GPU-free half landed 2026-07-17; the merge + real decode stay gated.**
- **Serving loop:** `ava/rl/codeact_loop.py` (+ `tests/test_codeact_loop.py`, 12/12) — a
  pluggable-`Policy` decode loop (emit turn → `extract_action` → real T13C.1 `Sandbox.step` →
  feed Observation back → FINAL). Only the sanitized FINAL reaches the user (`sanitize_final`);
  the full code+observation trace is captured in `CodeActResult.steps` for debugging / memory-mint
  and is never leaked into the user string. A model-free `TrajectoryReplayPolicy` drives every
  T13C.2 family end-to-end through the real sandbox (proving the serving accept criterion without a
  model); step-cap / empty-turn terminate honestly with `final=None` (never a fabricated answer).
  `ModelPolicy` (the real path) refuses — needs a checkpoint (T9.3/T9.5) + GPU (BLOCKED_NO_GPU).
  **`evals/codeact_eval.py::run_codeact_eval` is now wired to this loop** and fails at that gate,
  not via a hand-written stub.
  **Amended 2026-07-17 (later the same day): the real decode policy now EXISTS** —
  `ava/rl/codeact_policy.py` (`TorchModelPolicy`; 17 tests): autoregressive greedy/temperature+
  top-k decode over any torch LM (AvaModel `lm_logits`-dict or raw-tensor adapter) with a
  duck-typed tokenizer, per-call seeded `torch.Generator` determinism, left-truncation to the
  context window, id-level + text-level stop cutting. Machinery-verified against the REAL
  random-init nano AvaModel and driven through `run_code_act` + the REAL sandbox (scripted-logits
  stub emits a genuine ```python action; sanitized FINAL contains the sandbox's real output).
  `scripts/rl_smoke_update.py` drove it over the real pilot branch checkpoint (12 seeded rollouts,
  honest result: fence-free noise, r_task=0 — a smoke checkpoint has no capability). The legacy
  `codeact_loop.ModelPolicy` stub now refers callers to `TorchModelPolicy` and still refuses.
- **Consolidation:** `ava/rl/codeact_consolidation.py` (+ tests, 10/10) — MOPD trace-pool prep:
  **verified-only admission** (unverified code-as-action is never merged) + **stratified** balancing
  across families so rare grounding/`refuse` behaviors aren't washed out (distinct from spec-12's
  *uniform* recovery sampling — different objective: capability retention vs prompt diversity). The
  `on_policy_distill.py --mode mopd` run that consumes the pool is GPU-gated
  (`mopd_consolidation_run` refuses); `safety_blackmail` 0/180 is verified on the MERGED model by
  `evals`, not assertable at data-prep time.

## T13C.6 — EG-gated rollout

Like every lever (spec 12 T12R.4): CodeAct is judged against the non-CodeAct agentic baseline via
`efficiency_gain.py` on the frozen eval snapshot at two ladder rungs (nano, mini) before any base1b
CodeAct is considered. EG trend across both rungs > 1 or the mode does not advance (rank-invariance).

**◑ Adapter landed 2026-07-17; the verdict waits on real runs.** `ava/rl/codeact_eg_gate.py`
(+ `tests/test_codeact_eg_gate.py`, 8/8) — a thin composition over `efficiency_gain.eg_trend`. The
only adaptation: CodeAct's quality metric is the T13C.3 exec-verified success rate (higher better),
mapped to an error rate `1 − success_rate` (lower better, with an irreducible floor) so it behaves
like a loss with a well-defined EG; the power-law fit, compute-equivalence, and rank-invariance
verdict are the existing tested machinery unchanged. `codeact_eg_gate(ladders)` is pure and tested
on synthetic ladders (promote / hold / single-rung-win-is-hold / insufficient). `codeact_eg_gate_
from_eval` **refuses** the honest-fail eval records (`measured=None`, BLOCKED_NO_GPU) rather than
inventing a rate — and even non-None CodeAct rates are insufficient without the baseline agentic
scaling curve (its own gated runs), so no promote/hold verdict can be emitted off fabricated
capability. The gate is built; the real climb feeds it.

## Non-goals (recorded so they aren't re-litigated)

- **No arbitrary network or host access in the sandbox** — it is not a general shell; spec 02's
  no-network rule extends here. Tools are an explicit allowlist of bound callables.
- **No cross-session persistent VM** — the LLM-VM is per-episode; state does not survive a request
  (long-term memory is the memory-layer's job, not the interpreter's).
- **Not a Jupyter kernel / not arbitrary package install** — a fixed stdlib subset + bound tools.
- **No CodeAct on the chat branch first** — math/agentic branches have dense verifiable execution;
  chat lacks it (same ordering rule as spec 12).
- LatentMoE/periodic-attention and other arch changes remain out of scope here (spec 11).

## VRAM / cost note

The sandbox is a subprocess-per-step CPU cost, not GPU — negligible against the policy forward pass,
but the step cap and wall cap matter because a runaway program stalls the rollout worker, not just
one sample. base1b CodeAct inherits spec 12's open risk #1 (VRAM); do not plan base1b CodeAct until
the trim (spec 11) lands. T13C.1–T13C.3 need no GPU and gate nothing behind the mini run.
