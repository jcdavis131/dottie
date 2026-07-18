# Solo personal project, no connection to employer, built with public/free-tier only

# Mathematical foundations — mapping *Mathematics of Data Science* onto Ava (honest edition)

Source: "Mathematics of Data Science: Applied Engineering Extensions" (bridges Bandeira, Singer,
Strohmer to the Ava pipeline), reviewed 2026-07-17. Companion to `docs/RL_INTEGRATION.md`.

**Read this first — scope & accuracy guard.** The source doc is mathematically sound, but several
of its "Applied Engineering Extension" bullets describe a system Ava **is not**. Integrating it the
way this repo integrates everything (honestly) means separating four cases, not pretending the whole
thing already maps. The three buckets below are: **(A) genuine grounding** for mechanisms Ava
already has; **(B) actionable, in-scope candidates**; **(C) out-of-scope or architecture-mismatch**,
flagged plainly.

### Architecture reality check (so the mappings stay honest)

- **Ava is a from-scratch, dense-ish decoder-only transformer** — `AvaModel1B`: GQA + SwiGLU +
  YaRN RoPE, Multi-J-Space (S1/S2/Critic/Planner + Router/veto), next-token + J-space auxiliary
  losses. Trained on a **single consumer GPU** under **Docker**. Optional Gated-DeltaNet /
  compressed-KV are *arch candidates* (spec 11), not shipped.
- **Ava is NOT**: a Sparse-MoE *embedding* pipeline, a Matryoshka (MRL) embedding model, a 1-bit /
  binary-quantized vector database, a contrastive-embedding trainer, or a Modal-hosted service. The
  source doc's references to MoE routing "HR vs symbolic experts", MRL truncation, 1-bit Hamming
  recall, Modal containers, contrastive positive/negative pairs, and a "zero-trust Vercel edge
  access matrix" describe an **embedding/vector product**, not this repo. Where a bullet leans on
  those, it is bucket **C** — noted, not adopted.
- **`vector-hoops` is a separate project** (~527K-param tabular basketball model, no sequence, no
  KV-cache) and is **outside this ecosystem's repo scope**. spec 11 records that a prior session
  mis-filed content into it and reverted. Every "vector-hoops Application" bullet (Ch 5 spectral,
  Ch 6 diffusion maps, Ch 11 large-sample, Ch 12 SBM, Ch 15 compressive sensing) is therefore **not
  actioned here** — some have a real analogue inside our scope, called out where so.

---

## A. Genuine grounding — math that explains mechanisms Ava already has

These are the strong mappings: the theory is the *why* behind code that already exists.

- **Ch 8 — Gradient descent & convexity → the hill-climbing loop.** The macro loop (Conductor
  analyzes loss → adjusts a lever → runs a step) *is* a discrete descent, and `efficiency_gain.py`
  fits the loss-vs-compute curve it descends. **But** Ch 10 is the honest caveat: the true landscape
  is **non-convex**, so "local updates reliably reach the global optimum" does **not** hold —
  which is exactly the **rank-invariance finding** (`docs/RL_INTEGRATION.md`): a small-scale
  minimum can invert at scale. The math *endorses* the 2-rung EG gate over single-point descent.
- **Ch 4 — Tikhonov / ridge regularization → the RL trust region.** Spec 12's discipline system is
  regularization by another name: the **entropy thermostat** widens/narrows the trust region (the
  `λ` analogue is dynamic, driven by an integral controller on entropy), and the design deliberately
  avoids a KL penalty term — a *constraint-set* regularizer rather than a loss-additive one. PEFT-as-
  extreme-regularization ↔ Ava's **branch fine-tuning from a frozen stable checkpoint + MOPD**
  (`docs/DISTILLATION_INTEGRATION.md`): freezing the base and distilling is the ridge that stops the
  specialist overfitting its narrow synthetic validation set.
- **Ch 13 & 14 — Concentration of measure & matrix Bernstein → RL gradient-norm stability.** The
  **outer ratio clip** ("circuit breaker", spec 12 T12R.2) exists because unclipped GRPO branches
  permit **gradient-norm explosions** — precisely the spectral-norm tail that matrix Bernstein
  bounds. The clip is an engineered concentration guarantee: cap the per-step update magnitude so
  the sum-of-updates stays in-band with high probability. Ch 14's ensemble-variance framing also
  grounds MOPD consolidation (aggregating specialists without catastrophic aggregation error).
- **Ch 9 — SVM margin & the kernel trick → the J-Space Router.** The Router is a gate classifier;
  `routing_kl` health and the ShardMemo Tier-A/B/C **scope-before-routing** (ava-skills memory-
  router) are, in spirit, margin maximization — a wide-margin boundary routes reliably (code→code
  bias, safety→Critic) and degrades gracefully near the boundary. The **zero-init attention output**
  candidate (T11.8) is the init-time version of the same concern: keep token representations
  separable so the routing softmax has a margin to work with from step 0.
- **Ch 1 — The inverse problem `y = A(x) + ε`.** Fair framing for training-as-inversion: recover
  structured weights `x` from noisy loss observations. Philosophical grounding, not a code change.

## B. Actionable, in-scope candidates (filed, not speculatively built)

Genuine bridges that touch repos **in scope**. Filed here + in the owning repo's tracker; built only
when warranted, per the repo's "don't build speculatively" discipline.

- **Ch 5 & 11 — Graph Laplacian / spectral clustering → personal-graphify.** `cluster.py` today does
  Leiden → greedy-modularity. Spectral clustering (eigenvectors of the normalized Laplacian,
  `L x = λ D x`) is the principled third option, and Ch 11 says the discrete Laplacian converges to
  the manifold's Laplace–Beltrami operator as the graph grows — i.e. it stays meaningful as the code
  graph scales. **Implemented in this pass** as an additive fallback-chain backend (Leiden →
  spectral → greedy), because it is self-contained, low-risk, and directly uses the chapter. See the
  personal-graphify commit.
- **Ch 12 — SBM / BBP threshold → the EG promotion gate's noise floor.** `eg_trend` currently returns
  `promote`/`hold` on the *point* EG values. Ch 12's sharp signal-vs-noise threshold (and Ch 14's
  variance bound) is the missing piece: a 2-rung win inside measurement noise is *not* a win. Candidate:
  add an optional noise-floor / minimum-separation argument to `efficiency_gain.eg_trend` so a win must
  clear the run-to-run variance, not just exceed 1.0. Filed for `efficiency_gain.py`; not built now
  (needs real repeat-run variance data from the mini run to calibrate the floor honestly).
- **Ch 3 — SVD / Eckart–Young → spec 11 compressed-latent attention (T11.1).** Zaya1-style KV
  reduction *is* an optimal low-rank approximation of the K/V projections; Eckart–Young is the
  guarantee that the truncation is optimal in Frobenius norm. Also: **Orthogonal Procrustes** (SVD-
  based) is the right tool to align a new checkpoint's representation space to a legacy one without a
  full re-index — relevant if Ava ever versions its embedding/readout space. Filed against spec 11.
- **Ch 16 — Low-rank matrix recovery → eval-ledger gap-fill.** If `tasks/hillclimb-log.md` /
  `STATUS.json` eval history has holes (a crashed run), nuclear-norm completion could reconstruct
  missing validation scores so the hill-climb doesn't optimize on corrupted data. Low priority
  candidate; the honest default remains "don't optimize on a row you didn't measure."

## C. Out-of-scope or architecture-mismatch (recorded, not adopted)

- **Ch 2 (MRL truncation), Ch 7 (1-bit / JL random projection Hamming recall), Ch 10 (contrastive
  embedding training)** — describe an **embedding/vector-DB product Ava is not**. Ava is a next-token
  LM; it has no Matryoshka head, no binary-quantized vector store, no contrastive positive/negative
  objective. *Real analogue worth noting:* the JL lemma (Ch 7) and high-dim concentration (Ch 2) are
  the theory behind **compressed-KV** (spec 11 T11.1/T11.3) — dimension reduction that preserves
  pairwise geometry — so the *math* is relevant even though the *1-bit-quantization application* is
  not this system.
- **Ch 6 (diffusion maps), Ch 15 (compressive sensing) — vector-hoops** trajectory/geospatial
  applications. Separate project, out of this ecosystem's repo scope. Not actioned.
- **"Modal containers", "zero-trust Vercel edge access matrix" (Ch 8, Ch 13 bullets)** — Ava trains
  under **Docker on one local GPU**, not Modal; arxiviq is a **static** Vercel site with no access
  matrix. These bullets describe infrastructure Ava doesn't run. The concentration guarantee (Ch 13)
  still applies to *any* high-concurrency system, but there is no such Ava component to bind it to.

## Honesty note

The source doc is a good teaching bridge, but it consistently describes Ava as a Sparse-MoE
embedding/vector platform (MRL, 1-bit, Modal, contrastive, edge access matrix). That is not the
system in this repo. Adopting those bullets verbatim would be the same fabrication-by-alignment the
rest of this ecosystem's anti-mock discipline exists to prevent — so they are recorded in bucket C,
and only the mappings that match real code (bucket A) or warrant real work in-scope (bucket B) are
carried forward. One concrete build landed from it: spectral clustering in personal-graphify.
