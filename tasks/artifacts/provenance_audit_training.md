# Training-Data Provenance Audit — ava-factory (LLM pretraining pipeline)

**Scope:** `apps/ava-factory` training data pipeline. READ-ONLY, static + config only.
**Date:** 2026-07-24. **Auditor directive:** "always use real and verified data sources … garbage in, garbage out."

**Bottom line:** The **live** training pipeline is provenance-clean. Every synthetic
generator computes or curates its answers (nothing emits `np.random` noise or fabricated
facts as real signal), the curator is a genuine quality+decontam gate, and the frozen
tokenizer is hash-pinned through every shard. The real findings are **provenance-hygiene**
problems (a divergent dead second data path, stale/contradictory config labels) and a
**transparency** point (the honest mix is ~2/3 synthetic), not garbage feeding the model.

---

## Live data flow (what actually feeds the model)

```
collector (dottie/pipeline/collector.py, reads configs/sources.yaml)
  → RAW .jsonl.zst shards (per source, per phase, atomic publish, resumable cursor)
  → curator (dottie/pipeline/curator.py):
        normalize → is_english → gopher_quality → edu_score_ok → scrub_pii
        → dedup (MinHash-LSH, SQLite, cross-replica) → decontaminate (13-gram vs held-out evals)
        → pack (frozen BPE tokenizer, sha-pinned) → PACKED shards registered in manifest
  → dottie/train.py + StreamingShardSampler (dottie/data.py): claims PACKED shards
        by phase from the manifest, task_type-pure batches → model
```

Established from `docker-compose.yml:122` — trainer runs `python -m dottie.train --preset $AVA_PRESET --resume`.
The compose file itself warns (lines 62–64) that `python -m ava.train` is a **redirect stub that
trains nothing**; `dottie.*` is the live code. `dottie/train.py` maps token count → phase and the
sampler pulls packed shards by phase — it does **not** re-mix by `mini.yaml`'s `mix:` labels, so the
**effective mixture is governed by `configs/sources.yaml` weights** (what the collector wrote), not by
`mini.yaml`.

---

## 1. GENERATORS — `apps/ava-factory/dottie/datagen/` (18 in the `GENERATORS` registry)

All are HONEST-SYNTHETIC: private seeded RNG, byte-deterministic, answers **computed or
curated-correct**, schema-validated by `base.py` (`make_doc`/`validate_doc` fail loudly).

| Generator (source key) | Phases | Classification | Evidence |
|---|---|---|---|
| `logic` (synth_logic) | 0 | HONEST-SYNTHETIC | `logic.py:67 eval_formula` truly evaluates; truth tables via `itertools.product` (l.127); tautology/contradiction from real results (l.137-142); natded valid-by-construction; syllogisms by exhaustive model search (l.394). **Highest leverage: 100% of p0 (400M tok).** |
| `zk_math` (synth_zk_math) | 1,3,5 | HONEST-SYNTHETIC (gold) | `zk_math.py` every transcript computed; `assert lhs==rhs` (l.174,247), Merkle root recompute+`assert acc==root` (l.299), Lagrange `assert rec==secret` (l.350). Real `pow`/`hashlib`. |
| `math` (synth_math, synth_cot) | 1,3,4 | HONEST-SYNTHETIC | `math_gen.py` 4 asserts, numbers computed (geometric seq l.285 etc.). |
| `ency` / EncyclopediaGenerator (synth_facts, synth_needle) | 2,4 | HONEST-SYNTHETIC (curated real facts) | `encyclopedia.py` fixed fact tables, **correct** + asserted: legs 6/8/10/4/2/0 by class (l.22-77,164-165); capitals Bern/Canberra/Brasilia/Ankara (not the common-mistake answers) l.168-238. Single source of truth per entity → no self-contradiction. |
| `code` (synth_code) | 2 | HONEST-SYNTHETIC | `code_gen.py` `exec()`×5 to obtain **real** outputs (doctest-style), not templated. |
| `react_tools` (synth_react) | 2,3,5 | HONEST-SYNTHETIC | `react_tools.py` arithmetic computed (l.70), workflow totals `sum()` (l.303). `_FAKE_FUNCTIONS` (l.120) are **anti-hallucination grounding** — the correct answer is "it doesn't exist," not a fabricated fact. |
| `scout_cli` (synth_scout_cli) | 2,3,5 | HONEST-SYNTHETIC | `scout_cli.py` reproduces real `ok()/err()` envelope shape; payloads computed; only real plugins referenced (l.82-93); "fake" commands (frobnicate…) used for grounding (l.358). |
| `chat` / ChatSafetyGenerator (synth_safety) | 5 | HONEST-SYNTHETIC | `chat_safety.py` adversarial prompt → refusal pairs (l.161/169). Legit safety data. |
| `compression` (synth_compression) | 4,5 | HONEST-SYNTHETIC | 3 asserts; BWT/MTF/ANS derivations; textbook claims accurate. |
| `compress_trace` (synth_compress_trace) | 3 | HONEST-SYNTHETIC | 9 asserts; LZ77→Huffman step traces computed. |
| `db_trace` (synth_db_trace) | 3 | HONEST-SYNTHETIC | 14 asserts; LSM-tree/storage-engine sim traces computed. |
| `think_code`/`think_tools` (synth_think_code) | 3,4,5 | HONEST-SYNTHETIC | `think_in_code.py` `exec()`×2, computed outputs. |
| `tool_use` / ToolUseGenerator (synth_tool_use) | 2,3,4,5 | HONEST-SYNTHETIC | ReAct ladder; grounded/notfound families. |
| `wiki` (synth_wiki_px) | 2,3,4 | HONEST-SYNTHETIC | computed numbers (Kepler periods, equilibrium temps). |
| `jobbench` (synth_jobbench) | 3,4,5 | HONEST-SYNTHETIC | `workflow_jobbench.py` fictional-but-consistent delegation dossiers; no real-world fact claims. |
| `gaia2` (synth_gaia2) | 3,4,5 | HONEST-SYNTHETIC | `workflow_gaia2.py` fictional async scheduling scenarios; self-consistent. |
| `synpro` (synth_synpro) | 2,3 | HONEST-SYNTHETIC ⚠ (weight 0) | `synpro_gen.py` numbers computed via faithful-rephrase gate, BUT pairs **real exoplanet names** (Kepler-42 b, TRAPPIST-1 e) with **randomized** semi-major axis (l.19-32) → fabricated specific about a named real object. **Disabled (weight 0)**; harmless now. |

**Not in the live registry (no training effect):** `quality_taxonomy.py` contains "stub" classifier
descriptions but is **not imported by the live `dottie` pipeline** (dead/reference code).

## HF adapters (real→ReAct transforms) — `adapters.py` + siblings

Pure functions, network-free, provenance-honest. `glaive_adapt.py` preserves **real** function
responses as Observations and **drops** unparseable records (`return None`, "skipped honestly, never
patched", l.14/45/88). `xlam_adapt`, `swe_traj_adapt`, `conv_react`, `megawika_adapt` same contract.
Unknown adapter name **raises** (`adapters.py:35`).

## 2. HF (REAL) SOURCES — from `configs/sources.yaml`

| Source | Classification | License / gate |
|---|---|---|
| wikipedia_en, gutenberg_hist, pes2o, open_web_math, fineweb_edu (edu-score gated), github_code (Python-mit), cosmopedia, glaive_fc2, toolace, codeact_traj | REAL | permissive, `gated:false`; header claims each verified vs HF API (unverifiable in static audit — taken on config's word + license field) |
| proof_pile_2 (zstd decode error), megawika_en, xlam_react, swe_traj_react, tinystories | REAL but **weight 0** — QUARANTINED / not feeding the model | — |

## 3. CURRICULUM MIX (live: sources.yaml weights × mini.yaml token budget)

| Phase (tokens) | Real-web % | Synthetic % |
|---|---|---|
| p0 logic (400M) | 0% | 100% |
| p1 math (500M) | 50% (open_web_math) | 50% (math+zk) |
| p2 foundation (850M) | 55% | 45% |
| p3 reasoning (400M) | 15% | 85% |
| p4 long (150M) | 29% | 71% |
| p5 anneal (200M) | 19% | 81% |
| **Total 2.5B** | **≈34% real** | **≈66% honest-synthetic** |

All synthetic mass is computed/verified — honest — but the operator's "real and verified"
directive should note that **two-thirds of tokens are algorithmically generated**, not real-world text.

## 4. FROZEN TOKENIZER + SHARD MANIFEST — provenance intact

- `pack.py` loads the frozen tokenizer, computes its sha256, threads it to `manifest.complete(tokenizer_sha=…)`
  which raises `TokenizerMismatch` — a real freeze gate. Asserts `vocab ≤ uint16` (l.82) so ids can't wrap.
- All six held-out shards carry the **same** `tokenizer_sha` `d5ac2900…` and per-doc lineage
  (`doc_id = source:sha1(text)`, task_type, concept_token_id, phase). Verified in
  `data/mini/heldout_phase{0-5}.idx.json`.
- Decontam (`decontaminate.py`) is **real** held-out leakage prevention: 13-gram verbatim matching of
  training docs against `evals.eval_sets.EVAL_SETS`, with a fact-vs-prompt boundary that removes eval
  *prompts* without nuking the plain *facts*. Dedup (`dedup.py`) is real MinHash-LSH + exact-hash,
  persistent + cross-replica.

---

## VERDICT

**The LIVE mini pipeline is provenance-clean.** No generator emits random noise as
features/labels, no fabricated facts are presented as real, labels (task_type/phase/concept)
are validated at write time, decontamination is genuine, and the tokenizer is hash-pinned end
to end. The synthetic corpus is *honest*-synthetic (computed/curated), which is valid training
data. Issues found are hygiene/label-integrity and one transparency point — none is garbage
currently reaching the model.

### Top 5 issues (ranked by "garbage feeding the model" severity)

1. **Divergent DEAD second data path — latent footgun.** `streaming_data.py` /
   `trainer_agent.py` / `train_1b_deepspeed.py` carry a **15-trillion-token** schedule
   (`streaming_data.py:65-72`), source names matching **neither** sources.yaml nor the
   generators (`dclm`, `metamath`, `lean`, `long_docs_3x`… l.75-172), a **byte-level
   `SimpleTokenizer` stub** that bypasses the frozen BPE (l.232), and a **"mock training"**
   fallback (`trainer_agent.py:151`). **Not in the live docker pipeline** (compose runs
   `dottie.train`), so ZERO current impact — but anyone running `trainer_agent.py` against
   `data/streaming_shards/` would train on empty globs / mock data / wrong tokenizer.
   *Remediation:* clearly quarantine as "base1b scaffold, NOT wired," or remove.

2. **sources.yaml self-contradictory labels.** Header says "POST-MINI mixture — apply AFTER
   mini base_final … Live collectors must keep using sources.yaml until then," and inline
   comments say synth_tool_use is "ACTIVE here (post-mini). Live mini still uses sources.yaml
   at weight 0" — yet the file's own weights are **non-zero** and the collector reads this file
   unconditionally (`collector.py:194` default `/app/configs/sources.yaml`). So sources the
   comments call "disabled" (scout_cli, zk_math, tool_use) are actually **live**. Mislabeling,
   not garbage — but it can mislead an operator about what's training. *Remediation:* reconcile
   header/comments with the actual live weights.

3. **Two mixture specs that disagree; one is dead.** `mini.yaml` `phases[].mix` uses labels
   (`encyclopedia`, `tool_use`, `math_reasoning`, `long_docs`, `needle`, `proofs_verified`)
   that don't map 1:1 to sources.yaml source names, and the live sampler **ignores
   `mini.yaml.mix`** (pulls packed shards by phase). So `mini.yaml.mix` is descriptive text that
   no longer governs anything and disagrees with the real (sources.yaml-driven) mixture.
   *Remediation:* annotate `mini.yaml.mix` as descriptive-only or regenerate from sources.yaml.

4. **~66% of tokens are synthetic (transparency vs "real data" directive).** Honest-synthetic,
   but p0/p3/p4/p5 are 71–100% generated. If the directive intends real-world-text majority,
   the mix needs a policy decision. *Remediation:* confirm the synthetic-heavy design is intended
   (it is coherent for a reasoning/tool-curriculum small model; it is honest, just not "real-world").

5. **synpro: real exoplanet names + randomized orbital values (weight 0).**
   `synpro_gen.py:19-32` would teach false specifics about named real objects if enabled.
   Currently disabled → no impact. *Remediation:* switch to fictional planet names (as it already
   does for cities) before ever raising its weight.

### Out-of-scope note (not data-provenance)
`.env` commits a live `HF_TOKEN` (`apps/ava-factory/.env`). Secret-hygiene issue, flag separately.
