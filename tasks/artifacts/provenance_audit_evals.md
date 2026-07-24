# Provenance Audit — EVALUATION & PROBE Data Pipelines (READ-ONLY)

Date: 2026-07-24 · Scope: the data used to JUDGE models (evals, probes, judge, ledger eval).
Doctrine: "ALWAYS use real and verified data sources… garbage in, garbage out." Bad eval data
produces *fake confidence* and is as dangerous as bad training data.

Method: static read only (no execution, no model loads, no writes). Evidence is cited as
`file:line`. Where a risk is conditional, the condition is stated rather than asserted.

---

## Classification summary

| # | Eval source | Classification | One-line verdict |
|---|---|---|---|
| 1 | Heldout perplexity bins (`data/*/heldout_phase*.bin`, built by `scripts/build_eval_data.py`) | **BROKEN-OR-FABRICATED** (disjointness not enforced) | "Held-out" uses a hash key that the training split never honors → not provably disjoint from train. |
| 2 | Capability probe golds — arithmetic / modus_ponens / facts / code_out (`probe_items_gen.py`) | **SYNTHETIC-OK** | Deterministic, golds verified correct. Not real-world data, but honestly labeled. |
| 3 | Systems probe golds — db_mechanics / compression | **SYNTHETIC-OK** | Golds computed from training primitives + independently re-verified by a test. Correct. |
| 4 | Safety / tool_selection probe files | **SYNTHETIC-OK** | Hand-authored labels correct; `tool_selection.jsonl` is NOT machine-generated (latent drift risk). |
| 5 | Probe *scoring* mechanism (`probes.py` greedy exact-token match) | **caveat, not data** | ~0/200 is plausibly a brittle-scoring / weak-model artifact, NOT wrong golds. |
| 6 | agent-eval task specs + success_checks (`tasks/*/task.yaml`) | **REAL-VERIFIED** | Golds correct (12×11=132, etc.); checks are real deterministic conditions. |
| 7 | agent-eval scoreboard (`scoreboard.md` + `results/*.json`) | **BROKEN-OR-FABRICATED** | Stale schema AND an `status="error"` run is scored as a capability 0% datum. |
| 8 | The Judge (`scripts/judge.py`) | **REAL-VERIFIED** | Honest-None on unparse/backend error, records provenance, no fabricated verdicts. Not wired into scoreboard. |
| 9 | Research ledger eval (`research/evaluate.py`) | **REAL-VERIFIED (self-honest)** | Paired-seed gate + baseline-provenance/contamination flags. Flags the "4.5 placeholder"; does not hard-gate it. |

---

## 1. Heldout perplexity bins — disjointness is NOT enforced  → BROKEN-OR-FABRICATED

**What they are.** `build_eval_data.py:34 _collect_docs()` re-runs the five synthetic generators
(Logic/Math/Encyclopedia/CodeGen/ChatSafety) at fixed `SEED=1234` (same seed as `mini.yaml` `seed:1234`),
then selects "held-out" docs by its OWN hash:

- `build_eval_data.py:30-31` → `_bucket(doc_id) = int(sha1(doc_id).hexdigest(),16) % 100`, keep `< 2` (~2%).

The bins are real tokenized generator output (idx sidecars list genuine doc_ids, e.g.
`logic/truth_table:47f69b12…`; `tokenizer_sha` in the idx **matches** the frozen tokenizer —
`d5ac29…` == sha256 of `data/mini/tokenizer/ava_bpe_32k.json`). So the bins are not empty/placeholder.

**The defect.** The training corpus's canonical train/val/test split is a *different, uncorrelated*
hash:

- `dottie/pipeline/split.py:24-27` → `doc_fraction = int(sha1(doc_id)[:8],16)/2^32` (top 32 bits), placed
  cumulatively by `assign_split`, called by `dottie/pipeline/curator.py:223`.

`build_eval_data`'s `% 100 < 2` key appears **only** at `build_eval_data.py:31` — grep confirms it is
never used train-side. So nothing excludes the eval's held-out docs from the training "train" split.
A doc in the eval bin's bucket{0,1} is, under the *independent* split hash, ~train-ratio (≈90%) likely
to be assigned **train**. If training and eval share doc population (they do when both use the generators
at seed 1234), then the perplexity is being measured largely on **trained-on text**.

**Aggravating latent leak.** `build_eval_data.py:96-98` fallback: if a phase yields no bucket{0,1}
docs, it grabs `[d for d in docs if d.get("concept")][:50]` — arbitrary, *not* held-out docs — straight
into the eval bin.

**What it falsely tells us.** Falling per-phase PPL reads as "the model is learning to model language,"
when it is partly memorization of docs that were also in training. Even in the best case (training pulls
from real corpora, not these generators), the bins measure PPL on **synthetic** generator text, which
does not evidence real-text capability. Either way the number over-states confidence.

**Fix.** Make the eval derive "held-out" from the SAME key the pipeline splits on: import
`dottie.pipeline.split.assign_split` and take only `test`-split docs (or, symmetrically, have the curator
exclude `build_eval`'s bucket). Delete the `concept`-doc fallback (`build_eval_data.py:96-98`) — better a
"too short/missing" phase than silent leakage. Record in each idx whether every doc's `assign_split ==
"test"` as a provenance assertion.

## 2–4. Probe golds — SYNTHETIC-OK, golds verified correct

Golds are deterministic and spot-checked correct across every scored set:

- arithmetic `"82 - 38 =" → "44"`, code_out `"print(8 + 4) outputs" → "12"` (`probe_items_gen.py:317-349`).
- facts: all 20 country→capital pairs correct (`probe_items_gen.py:13-34`).
- modus_ponens: all 20 templates logically valid (`probe_items_gen.py:36-93`).
- db_mechanics / compression: golds **computed from the very training primitives**
  (`_fnv1a`, `_BTree`, `_lz77_encode`, `_varint`, `_huffman_codes` — `probe_items_gen.py:133-309`) so
  probe-truth cannot drift from train-truth, and `tests/test_probes_systems.py` **re-verifies** each with
  an independent re-implementation. Hand-checked: RLE `'DCCCCBBBBB' → "1D4C5B"` ✓, LEB128 `84855 →
  0xF7 0x96 0x05` ✓.
- safety.jsonl labels correct (threat→unsafe, benign→benign, `probe_items_gen.py:354-377`).

Honest classification: **SYNTHETIC**, not real-world — but that is exactly what they claim to be
(templated capability micro-probes), and they are decontaminated (their fixed stems are registered in
`evals/eval_sets.py:99-115` `SYSTEMS_PROMPTS`). No fabricated or mislabeled golds found.

Two caveats:
- `probe_items/tool_selection.jsonl` (mtime older than the 8 gen-written files) is **not** produced by
  `generate_probe_items()` — it is hand-authored and lives outside the deterministic regen path, so it can
  silently drift from any generator change. Golds sampled look correct (`get_clock` for UTC time, etc.).
- `_write_jsonl` comment (`probe_items_gen.py:110-112`) is worded backwards (claims `newline="\n"` causes
  CRLF translation — it prevents it); the *code* is correct and idempotent. Cosmetic only.

## 5. Probe scoring (~0/200) is a harness caveat, not a data defect

`probes.py:38-48` greedy-decodes exactly `len(ans_ids)` tokens *immediately* after the prompt and requires
an exact normalized match. This is brittle to tokenization/leading-space effects and to any preamble the
model emits. Because §2–4 prove the **golds are correct**, a 0/200 is attributable to genuine
nano/mini weakness and/or this brittle exact-match — **not** to broken/mislabeled probes. Interpreting
0/200 as "model can't do arithmetic" is only partly safe; it may also be "scorer too strict."

## 6. agent-eval task specs — REAL-VERIFIED

Task golds are correct and checks are real deterministic conditions:
- `no-tool-needed-arithmetic`: "What is 12 times 11?" → regex `132` (12×11 = **132**, correct;
  `tasks/no-tool-needed-arithmetic/task.yaml`).
- `fix-is-even-bug`: success = `pytest … -q` exit 0 (real shell check).
- `grounded-todays-date`: requires `get_clock` tool + date regex.
- `hallucination-resistance-fake-import`: requires read/grep tools + a "no import" refusal regex.

`test_task_specs.py` exists to guard the specs. No fabricated/wrong expected answers found.

## 7. agent-eval scoreboard — BROKEN-OR-FABRICATED (two defects, both confirm the GOAT audit)

**(a) Stale schema.** `scoreboard.md:13` per-task header is `| task | category | success | steps | tools |
notes |` — but the current writer `run_eval.py:206` emits a **`trajectory`** column. The committed
scoreboard predates the 2026-07-22 trajectory feature; it was not regenerated.

**(b) An errored run scored as a capability datum.** `results/ava_nano-chat.json` holds one row:
`task_id=no-tool-needed-arithmetic, status="error", success=False, "pattern='132' NOT matched"`. The run
**errored** (the HTTP-500-class failure the GOAT audit flagged), yet `score_task` (`run_eval.py:105-124`)
scores it `success=False` and `write_scoreboard` renders it as **"ava:nano-chat 0% (0/1)"**. An
infrastructure error is thereby laundered into a "0% capability" number — indistinguishable from a real
FAIL. The gold (132) is correct; the 0% is not a measurement.

**What it falsely tells us.** "The chat model scores 0%" — when in fact no valid measurement occurred.
**Fix.** In `score_task`, treat `result.status in {"error","harness_error"}` as **excluded/NaN**, never
`success=False`; the scoreboard should show `errored` separately from `0/N`. Regenerate the board so its
schema matches the writer, or add a schema-version assertion.

## 8. The Judge — REAL-VERIFIED

`scripts/judge.py` has genuine anti-fabrication guards: unparseable reply → `score=None` with raw text in
comment (`judge.py:49-62`), backend exception → honest `None` + error string (`judge.py:78-81`), and every
verdict carries `judge_model` provenance. No mock/placeholder path. Note it is a **standalone** module
(covered by `test_judge.py`); it is **not** wired into `run_eval.py`'s scoreboard, which scores
deterministically. So no judge-fabrication risk in the live scoreboard today.

## 9. Research ledger eval — REAL-VERIFIED, notably self-honest

`research/evaluate.py` evaluates candidates on real measured loss with real statistical gates:
- `_multi_seed_gate` (`:114-163`) demands paired-seed ab_nano evidence; within-run SEM alone can never
  promote (documents the historical false 4.4-SEM promotion of `5a7232ffea24`, later shown WORSE at all
  three seeds — `:50-61`). This is the "now gated" fix from the task; confirmed real.
- `_baseline_provenance` (`:166-183`) explicitly flags the **"4.5 hand-seeded placeholder"** baseline the
  GOAT audit named ("beat 4.5… on an explicitly-not-capability synthetic task — a meaningless promotion
  no gate caught"). **BUT it is "Recording only; not a gate"** — so a placeholder/contaminated baseline
  self-reports yet does not halt the loop.
- `_baseline_contamination` (`:185-238`) re-validates the experiment that set the baseline and honestly
  returns UNVERIFIED (not a false-clean) when the re-check skips stages.

The methodology and honesty are exemplary. Residual risk is inherited from the ledger baseline itself
(memory: REAL WINS = ZERO; the ratcheted baseline may still be an artifact), which evaluate.py *surfaces*
but does not *block*.

---

## Top false-confidence risks (ranked)

1. **Perplexity "held-out" is not disjoint from training** (§1). The eval's `sha1%100<2` key is unrelated
   to the pipeline's `sha1[:8]/2^32` split, and is never applied train-side. Falling PPL can be
   memorization, not learning. This is the single most dangerous eval-integrity gap because PPL is the
   loop's primary signal.
2. **Errored runs become capability zeros** (§7b). `status="error"` is scored `success=False` and shown as
   0%. Any eval-infra outage silently prints as "the model is bad" — and conversely masks whether a real
   0/200 is capability or plumbing.
3. **Baseline provenance is flagged but not gated** (§9). The "4.5 placeholder" and artifact-ratcheted
   baselines self-report yet still anchor promotions; a bad baseline confers false confidence on every
   subsequent "win."
4. **Latent leak fallback** (§1, `build_eval_data.py:96-98`): sparse phases silently backfill the eval bin
   with non-held-out docs.
5. **Scoreboard stale schema** (§7a): the published board no longer matches the writer; consumers may read
   the wrong column.

## Top fixes (highest leverage first)

1. Derive perplexity held-out from `dottie.pipeline.split.assign_split(...)=="test"` (the SAME key
   training uses); assert `test`-membership per doc in the idx; delete the concept-doc fallback.
2. In `run_eval.py score_task`, exclude `status in {error,harness_error}` from success math (NaN, not 0);
   render `errored` separately on the scoreboard; regenerate the board.
3. Promote `research/evaluate.py:_baseline_provenance` / `_baseline_contamination` from "recording" to a
   promotion **gate** (or require `calibrate-baseline` before any promotion counts).
4. Move `tool_selection.jsonl` into the deterministic `generate_probe_items()` regen path so it cannot
   drift; add it (and safety) to a re-verify test like `test_probes_systems.py`.
5. Fix the backwards `_write_jsonl` comment (cosmetic).

## What is genuinely clean (do not "fix")

- Probe golds across all six scored sets + safety (§2–4): correct, decontaminated, independently
  re-verified. The ~0/200 is not a mislabeled-probe artifact.
- agent-eval task golds (§6) and the Judge's anti-mock guards (§8).
- The research eval's paired-seed gate and honest baseline flagging (§9).
- Tokenizer provenance: heldout idx `tokenizer_sha` matches the frozen `ava_bpe_32k.json`.
