# Step 5 pre-registration — ONE encoder, per-domain LoRA, Matryoshka

Solo personal project, no connection to employer, built with public/free-tier only

Per the recommended sequence in `embedding_strategy_review_2026-07-26.md` §"Recommended
sequence": steps 1 (golden set), 2 (FTS5 baseline), 3 (Option C decision), and 4 (MinHash
dedup) are all done. Step 5 — train ONE encoder with adapters, hard negatives, held to
beating the golden-set baseline — has zero code as of this writing. This doc pre-registers
the target and methodology BEFORE the run, per the lesson item 5 of `TODO.md` names: a
number without a pre-registered target and protocol is not falsifiable after the fact.

## What already exists (reused, not rebuilt)

- `apps/ava-factory/scripts/ast_pairs.py` — (docstring -> function) pairs, `source: "docstring"`.
- `apps/ava-factory/scripts/hard_negatives.py` — SOURCE A (sibling: same_class < same_file <
  same_package) and SOURCE B (adjacent-commit) hard negatives, both proven never-a-positive.
  255 tests total across the two data-side modules (per `41afb54`).
- `scripts/retrieval_eval.py` — golden set miner (commit message -> changed files, walk-forward
  split, leak-free subset) + FTS5/bm25 baseline: **NDCG@10 0.622** (leak-free, commit-message
  queries, n=209).
- `scripts/task_eval_slice.py` — task-shaped queries mined from `TODO.md` itself, paths
  stripped so the query can't contain its own answer: **NDCG@10 0.429** (leak-free,
  task-description queries, n=87). This is the harder, more representative bar — the
  agent/site tier's real queries look like this, not like commit messages (§5.4 of the
  strategy review).

## Target (pre-registered, beat this or say so)

**Primary target: leak-free NDCG@10 on the task-shaped slice > 0.429.** The commit-message
number (0.622) is reported alongside for comparability but is NOT the bar — task_eval_slice.py's
own finding is that it flatters lexical retrieval. A result that beats 0.622 but not 0.429 is
not a win; say so plainly if that happens.

## Design decisions (made now, not deferred to code)

1. **Base encoder: `sentence-transformers/all-MiniLM-L6-v2`** (6-layer BERT, 384-dim, 22M
   params). Already in the local HF cache (`~/.cache/huggingface/hub/models--sentence-
   transformers--all-MiniLM-L6-v2`) from vector-unified's cultural-text warm-start — reused,
   zero new download. Loaded via `transformers.AutoModel`, not the `sentence-transformers`
   wrapper, so training stays a plain torch loop (matches the MTNN family's own style; no new
   runtime dependency beyond `peft`, which ships in the shared venv already, version 0.4.0).
   Not a code-specialised checkpoint (CodeBERT/CodeT5p would be), traded for zero-download and
   known-good-on-this-box; if the eval says it isn't enough, that is a legible reason to swap
   the base later, not a silent compromise.
2. **Two domain adapters, not N.** The review's own point (§ "a variety of models is the
   expensive form") applies one level down too — a LoRA adapter per micro-category would
   recreate the drift-surface problem inside one repo. Two domains map onto the two hard-
   negative sources already mined: `code` (ast_pairs docstring->function, sibling negatives)
   and `task` (commit-message/task-description->file, adjacent-commit negatives). Both sides
   of a pair use the SAME domain's adapter; base weights are frozen and shared.
3. **LoRA target modules**: `query`, `key`, `value`, `dense` inside each attention block
   (standard PEFT target set for BERT-family models). Rank 16, alpha 32, dropout 0.05 —
   defaults from the PEFT LoRA paper's ablations for encoder-only models this size, not
   tuned here; tuning rank is a cheap follow-up if the first run is close to the bar and
   underfit.
4. **Matryoshka nesting dims: [384, 256, 128, 64]** (native, then halved twice more). Loss is
   the sum of the domain's contrastive loss computed at each truncated+renormalised prefix,
   equal-weighted — no per-dim weighting scheme is claimed, since none has been measured on
   this task.
5. **Loss: multiple-negatives contrastive (InfoNCE)** per pair — positive + up to `--n-neg`
   mined hard negatives (default 4, matching `hard_negatives.py`'s `DEFAULT_N`) + in-batch
   negatives from the rest of the batch, temperature 0.05 (standard sentence-embedding
   default, not tuned).
6. **Adjacent-domain document text**: `hard_negatives.py`'s SOURCE B negatives are file PATHS,
   not text — the trainer reads each path's content at HEAD (same truncation, `MAX_DOC_CHARS`
   = 60,000, as `retrieval_eval.py`'s indexer) so the `task` domain trains on the same
   document representation the eval harness will score against.

## What this run is NOT claiming

Per the strategy review's own stated limits: the golden set's relevance is *sufficient, not
complete* (a commit's changed files, not every relevant file), so absolute recall is under-
measured — the comparison to the FTS5 baseline on the identical set is what's valid, not an
absolute quality claim. `all-MiniLM-L6-v2` is a general text encoder, not code-pretrained;
if it underperforms, that's informative, not a bug to route around before reporting it.

## Compute budget and go/no-go

Measured this box, 2026-07-31: RTX 4080 Laptop, 12.88 GB total / 11.6 GB free, torch
2.6.0+cu124, CUDA available and idle. Estimated corpus: ast_pairs over the monorepo (several
thousand pairs going by the 4,567-document minhash count) + ~300 golden commit pairs. A
22M-param base with LoRA adapters and batch sizes in the 32-64 range should be low-single-
digit GB VRAM and should not need multi-hour training for a first pass (a handful of epochs
over a few-thousand-pair corpus). **Not started without a smoke-tested pipeline first**
(`--smoke`: 2 epochs, capped pair count, must finish in well under a minute) and, per the
operator's own stated caution for this repo specifically (retrain requests here get more
scrutiny than the vector-X family — hours not minutes, and this is a still-unmeasured
first run), **the real run is held for an explicit go-ahead after the smoke test and this
plan are both in front of the operator**, not started automatically.

## Files this touches

- `apps/ava-factory/scripts/train_encoder.py` (new) — the training loop.
- `apps/ava-factory/scripts/embed_eval.py` (new) — scores a checkpoint against
  `retrieval_eval.py` + `task_eval_slice.py`'s golden sets using cosine similarity in place
  of bm25(), same walk-forward split, same leak-free subset, same NDCG@10/MRR/recall@10.
- `apps/ava-factory/requirements.txt` — add `peft` (already present in the shared venv,
  pinning it here makes the dependency legible instead of implicit).
- Neither touches `apps/ava-factory/dottie/**` or `apps/ava-factory/configs/**` (the FROZEN,
  bind-mounted paths) — this is a standalone retrieval encoder, not a change to the live
  Dottie LLM's own architecture.
