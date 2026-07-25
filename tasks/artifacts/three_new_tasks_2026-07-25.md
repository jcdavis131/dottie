# Three operator tasks, 2026-07-25 (content transcribed from screenshots — images are ephemeral)

## #1 — Gigatoken: what makes it special, re-evaluate our tokenizers, consider upgrading

**Claimed:** Rust BPE tokenizer. 24.53 GB/s on a 144-core AMD EPYC 9565, "against 24.8 MB/s for
HuggingFace tokenizers and 36.0 MB/s for tiktoken on the same machine". Marketing line on the chart:
"~1000x faster than HuggingFace's tokenizers, drop-in replacement."

**The three techniques (these are the transferable part):**
1. **Pretokenization without a regex engine.** Most tokenizers delegate pretokenization to a regex
   engine; Gigatoken does it directly:
   - a 256-byte lookup table classifies the first byte in O(1), replacing alt/backtrack dispatch
   - SWAR: loads 8 bytes as a u64 and checks all 8 for the letter property with branchless arithmetic
   - two independent cursors run from a safe split point so the out-of-order engine overlaps their
     instruction streams
   Its own optimization log, single-threaded GPT-2 pretokenization: fancy-regex 47 MiB/s -> NEON 462
   -> LUT+SWAR 830 -> dual-cursor 1,049 MiB/s.
2. **Pretoken caching.** Words seen before are looked up rather than re-encoded through BPE. Author
   notes this is the hard part: the cache grows quickly and pretoken distributions are long-tailed.
3. **Measured across hardware** (GPT-2, 11.9 GB OpenWebText): EPYC 9565 (144c) 24.53 GB/s ·
   Apple M4 Max (16c) 8.79 GB/s · Ryzen 7 9800X3D (16c) 6.27 GB/s.

⚠ **READ THE METHODOLOGY NOTE BEFORE BELIEVING THE HEADLINE — it is in their own post:**
"Gigatoken encodes the full file un-split and finds its own boundaries. HuggingFace tokenizers gets
the first 100 MB and tiktoken the first 1 GB, both presplit on `<|endoftext|>`. Best of 3 interleaved
rounds, fresh process per measurement."
So the three systems were given **different inputs** (12 GB vs 1 GB vs 100 MB) and different work
(self-boundary-finding vs pre-split). That is not an apples-to-apples throughput comparison.
⚠ **The headline and the chart disagree.** "~1000x faster" is claimed, but the chart on the same
image reads gigatoken **8.27 GB/s** vs tiktoken **61.5 MB/s** on M4 Max = **~134x**, not 1000x. Use
134x-as-charted at most, and only for the presplit-vs-unsplit caveat above.

**What to actually do:** (a) find what tokenizers this repo uses and where they are hot;
(b) decide whether tokenization is even on our critical path (if the trainer is GPU-bound at
~5k tok/s, a 100x faster tokenizer buys nothing); (c) only then consider adopting. The three
techniques are worth reading regardless — LUT+SWAR pretokenization and pretoken caching are
implementable without adopting the crate, and this repo's rule is zero new dependencies.

## #2 — Curriculum datasets in scikit-learn-Cookbook shape, from HuggingFace "open stack v3"

Rearrange the HF dataset into cookbook-style recipe format. **Target structure (transcribed TOC of
"Scikit-learn Cookbook — 80+ recipes for Machine Learning in Python, 3rd Edition", Packt):**
1. Common Conventions & API Elements of Scikit-Learn
2. Pre-Model Workflow and Data Preprocessing
3. Dimensionality Reduction Techniques
4. Build Models with Distance Metrics & Nearest Neighbors
5. Linear Models and Regularization
6. Advanced Logistic Regression and Extensions
7. Support Vector Machines and Kernel Methods
8. Tree-Based Algorithms and Ensemble Methods
9. Text Processing and Multiclass Classification
10. Clustering Techniques
11. Novelty and Outlier Detection
12. Cross-Validation and Model Evaluation Techniques
13. Deploying Scikit-Learn Models in Production

⚠ **AMBIGUITY TO RESOLVE FIRST:** "open stack v3" is not an exact HF dataset id I can confirm.
Candidates: `bigcode/the-stack-v2` (v3 not published as of this writing), an OpenStack-related corpus,
or something else. **Confirm the exact dataset id with the operator before ingesting anything** — and
note the standing license gate: any `*-ND` license is excluded (training is a derivative use) and
`*-NC` is excluded by default for the revenue mission. Shadow-library sources remain FORBIDDEN.

## #3 — Review our first/second-order derivative usage against the cheat sheet

Cheat sheet content (GRADIENT vs JACOBIAN vs HESSIAN), for checking our code against:
- **Gradient** ∇f, f: R^n -> R (scalar out). Vector of first-order partials, n x 1. Steepest-increase
  direction; magnitude = local rate of fastest increase. Uses: gradient descent, backprop.
- **Jacobian** J_F, F: R^n -> R^m (vector out). Matrix of first-order partials, m x n.
  row i, col j = ∂F_i/∂x_j. Local linear map: for small dx, dF ≈ J_F(x) dx. Uses: sensitivity
  analysis, local linearization, **Jacobian-vector products = forward-mode AD**, **vector-Jacobian
  products = reverse-mode AD / backprop**.
- **Hessian** H_f = ∇²f, f: R^n -> R (scalar out). Matrix of second-order partials, n x n square.
  Captures local curvature. Uses: Newton-type / second-order optimization, curvature analysis,
  **uncertainty approximations such as Laplace approximation**.
- Convention notes worth checking our code against: this table uses ∇f as a COLUMN vector and the
  Jacobian as rows=outputs, cols=inputs; other sources transpose. For scalar-valued f the Jacobian is
  1 x n (row) and under that convention the gradient is its transpose. If f has continuous second
  partials the Hessian is **symmetric** (Clairaut/Schwarz). At a local minimum the Hessian is positive
  semidefinite; positive definite is sufficient for a strict local minimum.

**What to review:** where we compute or approximate curvature — `apps/ava-factory/dottie/optim.py`,
`muon.py`, `jlosses.py`, and anything doing Laplace/uncertainty or a Newton step. Specifically: are we
conflating a Jacobian with a gradient anywhere (transpose/orientation bugs are silent), do we assume
Hessian symmetry where the function may not have continuous second partials, and do we assume positive
definiteness where only semidefiniteness holds.
