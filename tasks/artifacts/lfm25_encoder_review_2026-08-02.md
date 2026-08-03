# LFM2.5-Encoder (230M/350M) — reviewed against step 5, with a measured base bake-off

Solo personal project, no connection to employer, built with public/free-tier only

Operator forwarded Liquid AI's LFM2.5-Encoder release and asked to review and incorporate
the findings. It lands directly on a recorded blocker: `3492360` root-caused the step-5
encoder miss to the **base model**, and HANDOFF's next-attempt note says a real attempt
needs "a bigger corpus or a differently-suited base model". This is a candidate for the
second half of that sentence, so it was measured rather than argued about.

## 1. The headline number answers a different question than it appears to

The release is real and good. **LFM2.5-Encoder-350M: 4th of 14, 81.02 on a 17-task suite**,
above ModernBERT-base at 78.19, with three of the models ahead of it larger (one ~10x).

That suite is **GLUE, SuperGLUE and multilingual classification — not MTEB retrieval.** The
model card is explicit that this is an MLM-trained backbone and that the encoder body
(`Lfm2BidirectionalModel`) "needs a custom task head attached" for classification, retrieval
or similarity.

So 81.02 measures *"how good a fine-tuning backbone is this for classification-style NLU"*.
Step 5 asks *"does this beat lexical retrieval at NDCG@10"*. Both numbers are real; only one
of them is about the decision. This is the same shape as the other findings this session — a
real number attached to a different question — and it is worth naming because the ranking is
genuinely impressive and genuinely irrelevant here.

Two more mismatches, both specific to our setup:

- **`embed_eval.py` runs at `--max-len 256`.** The headline features — 8,192-token context,
  ~28 s vs ModernBERT's ~90 s per 8K pass on CPU — buy exactly nothing at 256 tokens.
- **bge-small, the current base, is contrastively trained for retrieval.** Swapping it for an
  MLM backbone removes the retrieval geometry LoRA is currently exploiting, and 574
  task-domain examples cannot rebuild that from scratch through a low-rank adapter.

## 2. The bake-off, and the result that actually decides it

Prediction registered before running: LFM2.5-Encoder-350M would score *below* bge-small
despite being ~10x larger, because capacity is not what is missing.

The LFM run could not be completed (§4). But the same experiment on three cached bases
answers the underlying question more directly, because it varies capacity **within a family
built for retrieval** — the best case for the "bigger base" theory:

Base-only (frozen, zero LoRA), all three scored today on the identical golden set, CPU,
task-shaped slice, n=101 / 93 leak-free, each at its own native dimension:

| base | params | native dim | task NDCG@10 | leak-free |
|---|---|---|---|---|
| all-MiniLM-L6-v2 | 22M | 384 | 0.1874 | 0.1768 |
| bge-small-en-v1.5 | 33M | 384 | **0.2293** | **0.2208** |
| bge-base-en-v1.5 | 109M | 768 | 0.2077 | 0.2048 |

**bge-base is 3.3x the parameters of bge-small and does not beat it.**

Stated carefully: with n=93 leak-free, a 0.02 spread is well inside what this eval can
resolve, so the honest reading is **not** "bge-small wins" — it is that **all three are
indistinguishable, and a 3.3x capacity increase bought nothing measurable.** That is the
finding. The bar is 0.429 as pre-registered, re-measured at 0.469 on 2026-08-01. Nothing in
this class is within 2x of it.

If tripling capacity inside a retrieval-tuned family moves nothing, a 350M MLM backbone with
no retrieval geometry is not the lever either. **The base-model branch of "bigger corpus or a
different base" now looks closed, which leaves the corpus branch.**

Harness validated before any of this was believed: MiniLM base-only reproduces at **0.1874**
against the recorded **0.186**. The recorded 0.265 is bge-small *trained*, not base-only, so
0.2293 base-only sits below it consistently rather than contradicting it.

**Golden-set drift is real and already documented** (HANDOFF: "the golden set drifts as
commits land", 0.429 → 0.469). Today's slice is n=101 where the recorded one was n=87, so
cross-day absolute comparisons are invalid. Every number in the table above was measured in
the same session on the same slice, which is the only comparison that is sound.

Incidental, but load-bearing for the Matryoshka design: bge-base scores 0.2048 at its native
768 and **0.1751 truncated to 384** — it is not Matryoshka-trained, so truncation costs real
accuracy. A base chosen for a Matryoshka pipeline should be one that was trained for it.

## 3. What IS worth taking

**Not as the step-5 retrieval base. As a CPU classifier, where the 81.02 is exactly on point.**
The model card's own demos are routing, linting, spell-checking and PII detection — all
classification, all CPU-only. The factory already does that work:
`apps/ava-factory/dottie/datagen`'s `clean.scrub_pii` plus curator dedup and quality
filtering. A fast 8K-context CPU encoder for **corpus curation** is a real fit, runs on the
CPU while the GPU trains, and is judged by the benchmark that was actually run.

**The decoder→encoder conversion recipe**, recorded as technique: causal mask → bidirectional,
short convolutions made non-causal with symmetric center padding, MLM at **30%** rather than
BERT's 15%. Applicable to any decoder, including ours, if an encoder is ever wanted from a
backbone we already trained. Low priority — our decoder is nano-scale — but the 30%-vs-15%
mask rate is a cheap, concrete finding to reuse if MLM pretraining ever happens here.

**License**, since monetisation is an explicit goal: LFM Open License v1.0 is Apache-2.0-based
with free commercial use **below $10M annual revenue**; above that requires a negotiated paid
licence, and fine-tuned derivatives inherit the terms. Not a near-term constraint, but it is a
term, and it is inherited — worth knowing before a derivative ends up in something sold.

## 4. Why the LFM number is missing, and it is not a modelling problem

**huggingface.co is unreachable from this box.** Measured 2026-08-02:

    https://github.com          HTTP 200
    https://pypi.org            HTTP 200
    https://huggingface.co      exit 35 (SSL connect error)
    https://cdn-lfs.huggingface.co   exit 6 (could not resolve host)

DNS resolves the apex to CloudFront (143.204.130.x) but TLS fails. Not the Claude Code
sandbox — identical with sandboxing disabled. MiniLM, bge-small and bge-base scored fine
because all three were already in `~/.cache/huggingface/hub`; LFM2.5-Encoder is not cached and
cannot be fetched.

**OPERATOR: this has a blast radius beyond this review.** `prefect_flows.py` pushes to the Hub
(`HF_TOKEN`, `--push`), and `apps/ava-factory/.env` holds a live token. Any HF pull or push
from this box fails today. That is worth fixing independently of whether LFM is ever tried.

To finish the measurement once HF is reachable:

    python scripts/embed_eval.py --base-only --base-model LiquidAI/LFM2.5-Encoder-350M \
        --trust-remote-code --device cpu --dims 1024,384,256,128,64 --json

## 5. DECISION

**Do not adopt LFM2.5-Encoder as the step-5 retrieval base.** Not on quality — on fit. It is
an MLM backbone benchmarked on classification, and the one capacity experiment available says
capacity is not the binding constraint.

**Do consider it for corpus curation**, where its actual benchmark applies and its CPU/8K
properties are advantages rather than irrelevancies.

**Reverses if** the LFM base-only run (command above) lands materially above 0.2293 on the
same-day slice. That would falsify the reasoning here, and it is one command to check.

**The real lever is now the corpus, not the base.** Three bases spanning 22M → 109M and two
families all land in 0.18–0.23 against a 0.469 bar. `3492360` called the ceiling a
*(base model, corpus)* pairing; this measures the base-model half and finds it flat.
