# Review: "train a variety of domain-specific embedding models, SOTA at retrieval"

Operator's proposition, reviewed rather than agreed with. Short version: **the idea is
right, the ordering is inverted, and "a variety" is the expensive form of a cheap idea.**

## Measured before opining

| fact | value | source |
|---|---|---|
| torch + CUDA on this box | **2.6.0+cu124, `cuda True`** | measured |
| GPU | RTX 4080 Laptop, 12,282 MiB, **0 MiB used** | `nvidia-smi` |
| RAM free / disk free | 1,896 MB / 23.6 GB | measured |
| lexical retrieval baseline | **already exists** — FTS5 in `bigbang/core/search.py`, `searchindex.py`, `cite.py`, `contentgap.py` | grep |
| retrieval eval (NDCG/MRR/recall@k) | **none anywhere** | grep |
| free eval supervision in git history | **696 of 817 commits (85%)** yield a usable (message → 1–8 files) pair | measured |

## 1. Where the idea is strongest — and what it actually commits you to

A small model trained on *your* corpus beating a large general model on *your* retrieval
task is a well-founded expectation, not optimism. Domain specificity is the real edge here.

But it silently changes the goal. "SOTA at retrieval" against CoIR leaderboards is not
reachable from one 12 GB laptop GPU, and chasing it would be a category error. **"SOTA on
our own eval set" is reachable — and it is unfalsifiable until that eval set exists.**
Right now it does not. So the first deliverable is not a model.

## 2. The ordering is inverted, and this session is the evidence

The binding constraint on this estate is not model capability. It is **the ability to tell
whether a change helped.** Today alone:

- all three recorded research `sota` rows turned out to be artifacts;
- `mtnn_report.json` says `promote {"ok": false}` and the artifact shipped anyway;
- the shipped hoops embedding is **transductive** — `"trained on all rows; NOT held-out"` —
  while the quoted metrics come from a different run;
- two published retrieval numbers for the same artifact (0.977 vs 0.846) use different
  splits and different loss sets.

Training N more models into that gap does not produce N more capabilities. It produces N
more unfalsifiable claims. **Build the measurement first — it is also the cheapest step.**

## 3. Measure the ceiling before paying for the model

You can know the value of an embedding model *before* training one:

1. **Golden set from git history.** 696 pairs already available: commit message = query,
   changed files = relevant documents. Free, domain-specific by construction, and
   **temporally splittable** — which matters enormously given the transductive finding
   above. Train/eval boundary by commit date, walk-forward, never random.
2. **Run the FTS5 baseline you already have.** scout-cli ships lexical search today.
   Score it on the golden set: NDCG@10, MRR, recall@10.
3. **Now the decision is quantified.** If BM25/FTS5 scores 0.70 on your queries, a served
   1.5B encoder has to clear that by enough to justify torch + weights + a serving path. If
   it scores 0.35, the case is overwhelming. Either way you stop guessing.

For code specifically, BM25 is a *strong* baseline — identifiers are high-signal literal
tokens. Anyone who skips this step is likely to attribute a win to embeddings that a better
chunker would have delivered.

**Caveat on the git-derived set, stated up front:** a commit's changed files are *sufficient*
relevance, not *complete* relevance — other files may be equally relevant and unchanged. So
it under-measures absolute recall. It is still valid for **comparing** two retrievers on the
same set, which is the only question being asked.

## 4. "A variety of models" is the expensive form of the idea

N domain models = N training runs, N eval sets, N serving paths, N drift surfaces. The
estate is **already showing drift strain at four domains**: three `vector-hoops` checkouts at
three commits, a binder that was unversioned until yesterday, and four published surfaces
advertising 48-d against a shipped 64-d artifact.

Cheaper shape with the same benefit:

- **One base encoder + per-domain LoRA adapters** — one eval harness, one serving path, one
  drift surface, and adapters are tens of MB rather than a model each.
- **Matryoshka (already in the guide)** gives you the truncation win (2048→512) without a
  second model.

Reach for genuinely separate models only when a domain's *tokenisation* differs enough that
adapters cannot bridge it — code vs prose plausibly qualifies; Python vs Go does not.

## 5. The scout-cli tension is real and is a product decision

scout-cli's identity is **zero new dependencies, stdlib-native** — 58 plugins, ~1,000 tests,
that constraint is the whole openswap thesis. An embedding model means torch + weights + an
inference runtime. That is not a minor exception; it contradicts the defining property.

Three honest resolutions, and this one is the operator's:

| option | cost |
|---|---|
| **A. Embeddings live in the factory; scout-cli calls an endpoint** | keeps scout-cli pure; adds a network dependency and an offline degradation path (the `DOTTIE_CHAT_URL` pattern already exists) |
| **B. ONNX runtime as an optional extra** | one dependency, opt-in; scout-cli's core stays stdlib but the doctrine gets an asterisk |
| **C. scout-cli stays lexical; embeddings serve the site/agent tier only** | zero doctrine cost; scout-cli never gets the capability |

Do **not** resolve this by building a `scout embed` that silently falls back to keyword
matching when the model is absent. That is the "gate whose verdict nothing consumes" pattern
wearing a new costume — a capability that reports success while doing something else.

### ✅ DECIDED 2026-07-26 — **Option C.** scout-cli stays lexical.

Operator's call. Embeddings serve the site/agent tier only; scout-cli keeps its
zero-new-dependency doctrine intact and FTS5 remains its retrieval path. The decision is
better-founded than it would have been an hour earlier, because the bar is now measured:
scout-cli's existing lexical retrieval scores **NDCG@10 0.622 / MRR 0.619 / recall@10 0.791**
on leak-free walk-forward queries. That is not a placeholder people are working around — it
is a decent retriever, and paying a torch dependency to replace it was never obviously worth
it.

**Consequences, so they are not rediscovered later:**

1. **No `scout embed`, no ONNX in scout-cli, no torch in scout-cli.** The doctrine holds
   without an asterisk. If this is ever revisited, revisit it against a *measured* margin
   over 0.622, not against a demo.
2. **`ast_pairs.py` stays in the factory and does NOT become a scout-cli plugin.** I proposed
   promoting it two turns ago; Option C cancels that. Extraction is training-data work, it
   belongs on the factory side of the boundary, and adding a plugin whose output only the
   factory consumes would blur the line this decision just drew. Work not done is the
   cheapest kind.
3. **The embedding model's consumers are now explicitly two**, and neither is scout-cli:
   (a) factory **data curation** — the mixture-coverage measurement in §6, which is the
   strongest argument in the whole proposal; (b) the **site/agent tier** on bhenre.com.
4. **A gap this creates, stated now rather than discovered during eval.** The golden set's
   queries are *commit messages*. That was the right proxy for scoring scout-cli's lexical
   search over a code tree. The agent tier's real queries are natural-language *task
   descriptions* ("why does the licence gate let ND through"), which are longer, less
   identifier-dense, and therefore **harder for BM25 and easier for embeddings**. The 0.622
   bar is honest for the set it was measured on and probably *flatters* lexical retrieval
   relative to the tier that will actually consume embeddings. Before step 5 is judged, add
   a second eval slice of task-shaped queries — otherwise the model gets measured against
   the one query distribution least favourable to it.
5. **Step 5 is unblocked.** Serving target is an endpoint, not an in-process import, which
   also means the model can be swapped or taken offline without touching scout-cli at all.

## 6. "Foundational to a better Dottie LLM" — true, but not by the mechanism implied

An embedding model does not initialise a better LLM; the objectives differ. The real
pathway is **data curation**, and it splits into two very unequal halves:

- **Dedup — cheap, and does NOT need embeddings.** MinHash LSH (the guide's Phase 8) is
  lexical and catches near-duplicates for a fraction of the cost. Do this first regardless.
- **Mixture coverage — this one genuinely needs embeddings, and it is the strongest
  argument in the whole proposal.** `configs/sources.yaml` assigns hand-set weights across
  six curriculum phases, constrained only to sum to ~1.0. Nothing measures whether P2 and P3
  actually cover *different* material. An embedding space over the corpus turns those
  asserted weights into measured coverage — overlap between phases, gaps, and which sources
  are redundant. That is a real, currently-blind decision surface.

## 7. "Faster agentic system" — restate it so it is measurable

Embeddings **add** per-call latency; they do not remove it. The win, if it exists, is
**fewer turns to a resolved task**, not lower wall-clock per call. Stated loosely, "faster"
will be claimed on the first demo that feels snappy. Stated as *median tool-calls per
resolved task, on a fixed task set*, it is falsifiable — and it is the number that actually
determines whether the agent got better.

## 8. The highest-leverage thing missing from the proposal: hard negatives

This separates a mediocre code retriever from a good one, and it is nearly free:

- **Sibling functions in the same file/class** — semantically adjacent, wrong answer. The
  `ast_pairs.py` extractor already knows the enclosing class, so these are one query away.
- **Adjacent-commit files** — files touched in commits near this one but not by it. Free
  from the same git mining that produces the golden set.

In-batch negatives alone teach "this function vs an unrelated function", which is easy.
Hard negatives teach "this function vs the one next to it", which is the actual task.

## Recommended sequence

1. **Golden set from git** (no GPU) — 696 pairs, walk-forward split by commit date.
2. **Score the existing FTS5 baseline** on it. Publish NDCG@10 / MRR / recall@10 with the
   protocol named, per the lesson from the 0.977-vs-0.846 split confusion.
3. **Decide the scout-cli integration option (A/B/C)** — blocks all serving work.
4. **MinHash dedup** on the training corpus — cheap, helps the LLM regardless of §5.
5. **Then** train ONE encoder with adapters, with hard negatives, and hold it to beating the
   §2 baseline on the §1 set. Pre-register the target number before the run.

Steps 1, 2 and 4 need no GPU and no decision. Step 5 is the only one that needs a model, and
by then it has a bar to clear that was set honestly.
