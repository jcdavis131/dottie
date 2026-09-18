# Tier 2 architecture: our own native function-caller ("needle-native")

## Why a byte-level model

Tier 1's grammar works at the **character level**. A byte-level language model
(vocab = 256 bytes + 3 specials) therefore matches the grammar exactly — no
tokenizer/grammar mismatch, the failure mode that haunts every BPE-based
constrained decoder. The model learns one job: *intent + tool schemas →
valid call JSON*.

## Model spec (v1)

| Field | Value |
|---|---|
| Architecture | Decoder-only transformer, pre-norm, RoPE |
| Layers / d_model / heads | 8 / 256 / 8 |
| FFN | 1024 (SwiGLU) |
| Context | 512 bytes |
| Vocab | 259 (bytes + `<pad> <bos> <eos>`) |
| Params | ~6.5M ≈ **26 MB fp32**, ~7 MB int8 |
| Objective | Cross-entropy on **completion bytes only** (prompt masked) |

Size rationale: Needle's headline is 8–29 MB. 6.5M params at fp32 lands at
26 MB — same weight class, honest fp32, no exotic quantization needed for v1.

## Training data

`make_data.py` (stdlib, runs anywhere) derives every pair from Dottie's real
tool catalog — intent paraphrases × schema-sampled argument values. Split
discipline: **held-out tools**, not held-out intents. The eval tools
(`reward_compute`, `approval_consume`, `dataset_release`, `incident_drill`)
never appear in training, so the eval measures true schema-following
generalization rather than memorized tools.

## Confidence — the Needle trap we don't repeat

Needle's headline "4L matches DeepSeek" config fine-tunes the model and
**silently kills its confidence head** — you lose the safety signal exactly
when you ship. Our design:

- Primary signal: mean token log-probability over the emitted **call span**
  (the reasoning trace is excluded — it was never constrained).
- Calibration: isotonic regression fit on the eval split; we report **ECE**
  (expected calibration error), not vibes.
- Contract (from the QA reconciliation): confidence is a **scrutiny-path
  signal** (which review lane a call takes). It never authorizes anything —
  Dottie's deterministic approval gates keep that job.

## Inference: where Tier 1 pays off twice

v1 inference = Tier 1's guided loop with our sampler: generate → extract →
validate → repair → fail closed. The eval's ablation (raw greedy vs.
grammar-loop) directly measures what the grammar mechanism is worth on our
own weights.

v2 inference (follow-up, spec'd not built): **per-step grammar masking**.
This needs a `GrammarCursor` — an incremental view over the Tier 1 parser
exposing `feed(byte)` and `allowed_next_bytes()` at each step. The parser
already tracks position/state; the cursor is mechanical but not yet written.
With it, invalid becomes *unreachable* (Needle's true property), not merely
*rejected*.

## Honest non-goals for v1

- No chat, no classification, no judgment — System-1 tool router only.
- No multilinguality beyond what the catalog's English descriptions carry.
- The model never sees secrets; argument values are brokered references,
  exactly as in `dottie_loop`'s tool plane.
