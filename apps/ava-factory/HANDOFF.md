# Handoff — Ava continuous pipeline

Paste the block below into a fresh Claude Code session started in `C:\Users\jcdav\ava-agi`.

---

You are the foreman on the Ava AGI Factory project at `C:\Users\jcdav\ava-agi` (branch
`claude/model-training-workflow-plan-n5vep5`, also pushed to `master`). Read `PLAN.md`,
`TODOS.md`, and `ORCHESTRATION.md` first — they are current and accurate. `specs/` holds the
per-stage contracts used to dispatch sub-agents.

## What this is

The repo began as a *blueprint*: a mock trainer (`loss = torch.tensor(1.0)`, checkpoints written as
text files), hardcoded eval scores, no tokenizer, a `server.py` that `NameError`s on import. Stages
0–6 have turned it into a real system. The goal is a Multi-J-Space transformer trained on a
continuous gather → clean → train → serve pipeline, on the local RTX 4080.

## State: Stages 0–6 done, verified, committed

Five Docker services coordinated by a SQLite manifest with atomic leased claims
(`ava/pipeline/manifest.py`). Collector streams HF + runs deterministic synthetic generators;
curator cleans/dedupes/decontaminates/splits/packs to uint16 shards; trainer consumes them live;
janitor reclaims disk. **The nano smoke run passes on the GPU**: 13.79M params, lm loss
9.053 → 3.400 in 30 steps at ~18–20k tok/s, checkpoint written, `--resume` verified.

Tests: **119 CPU + 83 GPU**, all green. Run both — the two images carry deliberately disjoint deps
(see `tests/conftest.py`):

```bash
make test          # = test-cpu + test-gpu
```

## Non-obvious environment facts (measured, do not re-derive)

- **HuggingFace connection-resets from the Windows host but works reliably inside Docker.** Docker
  is the network fix, not just packaging. All HF I/O happens in containers.
- HF streaming requires exactly `datasets==2.20.0` + `pyarrow==16.1.0`. Unpinned → `NoneType.ArrowInvalid`.
- `--gpus all` passes the 4080 into containers. Train there.
- **Never run `docker system prune --volumes`** — the 29 volumes are other projects' live data
  (`p0_postgres_data`, `p0_neo4j_data`, `p1_minio_data`, `p2_pgdata`, …). `docker builder prune -a`
  is safe (reclaimed 25GB).
- The `python3.11` process holding ~1.8GB of VRAM is the user's **live** vector-hoops sweep
  (`sweep_v5.py --resume`). Do not kill it. nano/mini coexist; base1b will need it gone.
- Git Bash `/tmp` is invisible to Docker. Mount from the repo dir. Container paths in
  `-e VAR=//path` need the `//` prefix to defeat MSYS path mangling.
- Disk is the binding constraint (~27GB free, single drive).

## Working agreement that has been earning its keep

**Assert the property, not the absence of a crash.** Three defects in this repo "passed" for years
by being unobservable: attention had no causal mask; the workspace broadcast the future into the
past; `verbalizable_mass` was the constant `0.06`. None raised. Since then, every bug found has come
from *running* the thing, not reading it — including one I wrote myself (a `modulation` loss term
computing `cos(x, x)`, hence identically 1, hence a hinge that could never fire).

So: validate tests with negative controls (weaken the implementation, confirm the test screams —
this is how `BEGIN IMMEDIATE` in the manifest was proven load-bearing). Report measured numbers.
Never claim a test passed without running it.

Sub-agents are dispatched per `ORCHESTRATION.md` (🟪 Opus for correctness-critical, 🟦 Sonnet for
mechanical). Paste the existing API surface into their prompts — they invent their own otherwise.
Workers are told deviations are welcome if justified: the curator agent overrode its spec's crash
ordering and was right.

## Next work, in order

1. **Stage 7 — real eval harness** (`evals/`, 🟪). Replaces `eval_branch_harness.py`, where every
   score is a literal and the "intervention engine" edits a `torch.randn` matrix indexed by
   `sha256(concept) % vocab` — it never touches the model. Deliver `perplexity.py` (val in-training,
   test at milestones only), `probes.py`, `interventions.py` + `jspace_tests.py` (the 5 canonical
   tests as real forward-hook measurements using **real tokenizer ids** via
   `AvaTokenizer.concept_token`), `needle.py`, `run_harness.py`. Plus `tests/test_no_mock.py`, which
   must fail if any mock literal (`0.82`, `0.983`, `0.91`) appears unconditionally.
   Contract: `specs/06_evaluation.md`. **Do not inherit the old PASS bars** — they were tuned for a
   14M synthetic model. Report measured values.
2. **Stage 8 — live serving** (`ava/serve_engine.py`, `server.py`). `server.py` currently uses
   `Optional` without importing it. Migrate `InterveneReq` to pydantic v2 `Field(alias="from")`,
   wire every endpoint to the engine, keep the `ENABLE_JSPACE_WRITE=1` + `?mode=research` 403 gate,
   add `/health` `/generate` `/report`, hot-reload `ckpt/latest` so the model can be probed *while it
   trains*. Contract: `specs/07_serving_deployment.md`.
3. **T5.4** `scripts/bench_pipeline.py` — gate: curation tok/s ≥ 3× trainer tok/s.
4. **T6.5** `ava/pipeline/janitor.py` — disk watermarks, delete CONSUMED (never val/test), ckpt rotation.
5. **Stage 9** — full nano run, then mini (171M, ~2.5B tokens, 3–5 days), then the base1b GO/NO-GO.

## Open decisions for the user (do not decide alone)

- **`.wslconfig` is written but not applied.** Needs `wsl --shutdown`, which stops Docker and every
  distro. Ask first.
- **base1b is 1409M, not the 1.17B the spec claimed.** The specs undercounted the J-Space: each of 4
  workspaces carries `10·d_model²`, plus 4 cross-attentions at `4·d_model²` (~235M at d=2048). That's
  8.4GB of weights+grads+AdamW8bit before activations, against ~11.6GB free. Options: drop
  `n_fusion_layers` 28→24 (−92M), or narrow the workspaces. Decide at the Stage 9 gate, with mini's
  eval report in hand.

## Known limitations, stated honestly

- `--resume` is **loss-continuous, not bit-exact**. Model/optimizer/step/phase/RNG restore exactly,
  but the sampler claims from a manifest collectors are still writing to, so data order can't be
  reproduced. Bit-exactness needs an as-of manifest watermark (TODOS T10.5).
- At base1b (~100M tok/day) **data production may not outrun the GPU**. Under single-pass
  delete-after-consume, supply falling behind consumption means silent replay — i.e. memorization.
  Measure at mini; don't assume. (TODOS Stage 10, `specs/10_continuous_supply.md`.)
- Only `tinystories` (HF) and the synthetic sources have been live-streamed. The other five HF
  sources are API-verified but never pulled; `fineweb-edu`'s `score` field name comes from the spec,
  not from an observed record.
- nano's loss falling to 3.4 in 30 steps reflects how templated the phase-0 truth-table corpus is,
  **not** model quality. Real signal comes from val PPL and the probes — i.e. Stage 7.

Start by reading `TODOS.md`, running `make test` to confirm the tree is green, then pick up Stage 7.
