# Experiment 2607.14087v1 — Stochastic Domination of Gaussian Maxima: A Resolution to the Weak Simplex Conjecture

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul17-graphify-rag-2607.140
**Date:** 2026-07-17 — expanded 2026-07-17 16:50 CDT
**Paper:** https://arxiv.org/abs/2607.14087v1 / PDF https://arxiv.org/pdf/2607.14087v1
**Topic:** graphify-rag — Graphify + GraphRAG + Knowledge Graphs for LLMs (importance critical)
**Ecosystem:** bigbang-cli/docs/llm-wiki/ + ~/your_files/personal-graphify + ava-research-engine/scripts/graphify_research.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14087v1.md
**Current Graphify Build:** 170 files → 1118 nodes / 2295 edges / 102 communities, 1132.8 KB graph.json, queries validated: Muon 44n/97e 50.9x, GraphRAG 60n/62e 37.3x (top: 2507.03226v2)

## Abstract (from paper)
We prove a stochastic comparison for Gaussian maxima. Let R be m×m correlation matrix satisfying R - 11^T/m ⪰0, let X∼N(0,R), and Z_i independent standard Gaussians. Then max_i X_i ≤_st max_i Z_i, equivalently P{X_i ≤ c ∀i} ≥ Φ(c)^m ∀c. This comparison resolves the Weak Simplex Conjecture: among d+1 equiprobable equal-energy signals in R^d over AWGN, the regular simplex maximizes probability of correct ML decoding at every SNR. It also proves Simplex Mean Width Conjecture and gives exact formula for largest number of equiprobable messages that can be sent at prescribed energy and error probability by deterministic no-feedback AWGN code under per-codeword energy constraint. Proof combines Gaussian product inequality for log-concave functions with adaptive tilting argument making inequality applicable to one-sided threshold events defining the maximum.

## Why relevant to graphify-rag / personal-graphify
- **Current system:** personal-graphify: upstream 727 nodes 1713 edges 49 comms / current build 1120 nodes 2295 edges 102 comms. Token estimate ~1500 per scoped query vs ~90000 naive → 60× reduction (mirrors 71.5× upstream). God nodes: Ava AGI Factory v6.4 degree 121, Critic hl30 degree 64, Personal Graphify degree 46. Built via tree-sitter + # NOTE/# WHY comments as first-class nodes.
- **Problem:** GraphRAG retrieval must bound error when retrieving top-k communities/nodes under correlated embeddings. Current pruning is heuristic. Need principled bound for "largest number of messages (nodes) we can retrieve at prescribed token budget and error probability" — exactly the AWGN coding result this paper gives.
- **Embedding geometry:** Weak Simplex result says regular simplex (d+1 points equally spaced on sphere, pairwise dot = -1/d) is optimal for ML decoding under Gaussian noise. This maps directly to: 
  - Optimal arrangement of community centroids / J-Space archetypes (S1 Fast hl8, S2 Slow hl300, Critic hl30, Planner hl150) on d-sphere to maximize separability.
  - Optimal codebook for vector search — 4 workspaces → regular tetrahedron is optimal, not orthogonal.
  - Our current router targets: automatic [0.6,0.15,0.1,0.15] deliberate [0.15,0.55,0.1,0.2] etc — could be simplex-weighted.
- **Stochastic domination bound:** Condition R - 11^T/m ⪰0 means correlation matrix dominates simplex (all pairwise correlations ≥ -1/(m-1)?). When community embeddings satisfy this (almost regular simplex), max retrieval score distribution is dominated by independent case → we can bound P{all scores ≤ c} ≥ Φ(c)^m. Gives safe pruning: if Φ(c)^m ≥ 1-ε, we can drop m nodes with error ≤ε using only independent Gaussian tail, no need to estimate full correlation.

## Paper Deep Dive — Simplex Optimality

**Core theorem:** If R ⪰ 11^T/m (in PSD order), then max of correlated Gaussians is stochastically smaller than max of independent Gaussians. Intuition: correlation reduces variance of max (positive correlation helps all stay below threshold together). Condition means R is more "spread out" than simplex correlation (-1/m on off-diag after centering). Regular simplex correlation = I - 11^T/(d+1) scaled? Actually simplex has R_ij = -1/d for i≠j, which satisfies R - 11^T/(d+1) = I - 11^T/d - 11^T/(d+1)... need check, but paper shows it satisfies.

**Connection to coding:** AWGN channel: transmit one of m equal-energy signals s_i (||s_i||^2 = E). Receive y = s_i + N. ML decoder picks max correlation <y, s_j>. Correct decoding iff N correlates most with true s_i than any other difference. Distribution of max of correlated Gaussians X_j = <N, s_j - s_i> determines error. Minimizing max error → minimize tail of max X. Paper shows simplex minimizes that tail at all SNR → optimal code.

**Mean width:** Expected max <g, s_i> for g Gaussian = mean width of simplex. Inequality proven.

**Proof ingredients:**
1. Gaussian Product Inequality (GPI) for log-concave symmetric functions: E[∏ f_i(X_i)] ≥ ∏ E[f_i(X_i)] when R satisfies condition? But GPI is for even log-concave.
2. Adaptive tilting: shift Gaussian by c·1 to turn one-sided threshold {X_i ≤ c} (not symmetric) into product of symmetric-ish functions via exponential tilting e^{<a,X>}. Choose a to make inequality applicable.
3. Combine to get P{X_i ≤ c ∀i} ≥ Φ(c)^m.

**Implication:** Exact formula for M*(E, ε) = max number of messages at energy E, error ε under per-codeword power constraint, deterministic, no feedback. Inverse of Gaussian tail: M = max m s.t. Φ^{-1}(1-ε)^{?}. Paper gives M = largest m with something like Φ(c)^m ≥ 1-ε where c relates to sqrt(2E)/σ.

For Graphify: This gives formula for largest number of graph nodes we can keep in context at token budget (energy) and retrieval error ε.

## Hypothesis for graphify-rag
> Applying simplex optimality and Gaussian maxima domination bounds to personal-graphify will let us (1) arrange J-Space + community embeddings as regular simplex for max separability, (2) use Φ(c)^m bound for safe token pruning with provable error guarantees, (3) compute exact M*(token_budget, ε) for GraphRAG, improving token reduction beyond 35.2× while preserving recall.

Fixed budget: 5 min wall clock, ONE file change, metric = graph query recall + token reduction.

## Design Options (single-file constraint per program.md)

### Option A — scripts/graphify_research.py — simplex pruning (recommended, lowest risk)
Add function `simplex_bound_prune(c, m, epsilon)`:
```python
# From arxiv:2607.14087v1 — Weak Simplex Conjecture resolution
# If R - 11^T/m ⪰0, then P{max X_i ≤ c} ≥ Φ(c)^m
# Use to bound retrieval error: we can prune m nodes if Φ(c)^m ≥ 1-ε
import math
from mpmath import quad, erfc, sqrt
def phi(c): return 0.5*(1+math.erf(c/math.sqrt(2)))
def safe_prune_threshold(m, epsilon):
    # solve Φ(c)^m ≥ 1-ε → c ≥ Φ^{-1}((1-ε)^{1/m})
    target = (1-epsilon)**(1.0/m)
    # approx inverse normal
    return math.sqrt(2)*math.erfcinv(2*(1-target)) # or use scipy
```
In build: after pgraphify query, compute correlation of community centroids, check if R - J/m PSD (via eigh). If true, use independent bound to set threshold c instead of empirical.

Pros: 20 lines, no model change, improves token reduction provably. Cons: need correlation matrix from embeddings.

Complexity: low.

### Option B — personal_graphify embedding layout — regular simplex regularization
In `personal_graphify/embedder.py` or graph builder, add simplex loss when building archetype centroids:
```python
# From arxiv:2607.14087v1 — regular simplex maximizes ML decoding probability
# Arrange 4 J-Space workspaces as tetrahedron on sphere: dot = -1/3 for d=3
import torch
centroids = torch.stack([S1_mean, S2_mean, Critic_mean, Planner_mean]) # [4,d]
centroids = F.normalize(centroids, dim=1)
# target Gram = I*(1+1/3) - J*(1/3)? Actually -1/3 off-diag for tetrahedron
target = torch.eye(4) - (1/3)*(torch.ones(4,4)-torch.eye(4))
simplex_loss = F.mse_loss(centroids @ centroids.T, target.cuda())
# Add to j_weight: loss += 0.1 * simplex_loss
```
This directly implements Weak Simplex optimality for J-Space routing.

Pros: aligns with Ava multi-jspace hl=8,300,30,150. Cons: touches model file.

### Option C — graphify-out-research combined context — M*(E,ε) token budget formula
Use exact AWGN capacity formula from paper to compute max nodes M for given token budget E (energy) and error ε:
```python
# From paper: M*(E,ε) exact formula under per-codeword energy
# Translate: E = token_budget, ε = retrieval_error
# Use paper's theorem to compute M
def max_nodes_for_budget(token_budget, epsilon, snr=1.0):
    # c = sqrt(2E/N0) etc — approximate
    # For now: M ≈ floor( log(1-ε) / log(Φ(c)) )
    ...
```
Integrate into `research_task_synth.py` to create tasks only if within bound.

Most novel but higher complexity.

**Chosen for first smoke:** Option A in `scripts/graphify_research.py` — add `phi`, `safe_prune_threshold`, log when bound holds, comment cites paper. Keep existing build intact, just adds validation log.

## Implementation Plan (5min)

1. `cd ava-research-engine && git checkout -b autoresearch/jul17-graphify-rag-2607.140` (branch exists)
2. Edit `scripts/graphify_research.py`:
   - Add top comment `# From arxiv:2607.14087v1 — Stochastic Domination of Gaussian Maxima, Weak Simplex Conjecture → simplex is optimal for AWGN decoding, bound Φ(c)^m`
   - Add functions `phi(c)`, `inv_phi(p)`, `check_psd(R - J/m)`, `safe_prune_m(c, eps)`
   - After each `pgraphify query`, compute mock correlation check if log shows community centroids available? For smoke, just compute example: for m=60 nodes, ε=0.05, find c = Φ^{-1}((0.95)^{1/60}) ≈ ?
   - Log `[simplex-bound] m=60 ε=0.05 → c=2.... Φ(c)^m=0.95 safe to prune threshold ..`
   - No break of existing build — additive logging only
3. Commit: `exp: graphify-rag 2607.14087v1 — simplex optimality + Gaussian maxima bound for pruning`
4. Run smoke: `python3 -m ava.config --preset nano --count-params` OK (already via runner)
   Then: `python scripts/graphify_research.py 2>&1 | tail -30`
5. Metrics: grep `^\[simplex-bound\]` and graph stats `Nodes: .* Edges:`
6. Log to results.tsv: commit hash, reduction factor, status keep/discard, description "simplex bound Φ(c)^m for m=60 ε=0.05, regular simplex optimal for 4 J-Space workspaces"

## Expected Outcome

- If validated: query results still 44n/97e Muon, 60n/62e GraphRAG, etc., plus new `[simplex-bound]` logs appear. Token reduction stays 60× or improves to ~65× with safe pruning — keep branch, create [AVA-EXP-KEEP] and update `bigbang-cli/docs/llm-wiki/research-latest.md` with simplex result.
- If graph.json size stable 1132.8 KB and no regression: log keep.
- If check fails (PSD condition not met): log discard with reason "correlation R - J/m not PSD for current embeddings, simplex not applicable without re-embedding to regular simplex first" — still valuable, suggests Option B re-layout needed.

**Connection to 2607.14086v1:** Both deal with unlabelled / limited data — 14086 uses SSL to leverage unlabelled, 14087 uses geometry of embeddings to maximize separability with limited energy (tokens). Together: use SSL pretraining + simplex arrangement for optimal few-shot GraphRAG.

## Risks & Mitigations

- PSD check needs numpy — not available in minimal env: mitigate by using simple heuristic: if max off-diag correlation < -1/(m-1)+δ, assume simplex-like.
- Inverse Phi approximation may be inaccurate without scipy — use `math.erfcinv` or simple binary search, tolerance 1e-3 fine.
- Over-pruning risk: independent bound Φ(c)^m is lower bound, so using it is conservative (safe) — won't prune too aggressively, so recall safe.
- Complexity creep: keep to ≤25 lines added, ONE file.
- Branch already exists (autoresearch/jul17-graphify-rag-2607.140) — need to commit on top, not recreate.

## Next Steps if KEEP

- Wire simplex arrangement into `multi_jspace_module.py`: force S1/S2/Critic/Planner means to regular tetrahedron via loss term 0.1 * MSE(Gram, target=-1/3 off-diag) — directly implements Weak Simplex Conjecture optimality for 4 symbols.
- Update `personal-graphify/references/spaces/research-graph.json` node for this paper with degree links to Ava J-Space, Graphify, Multi_JSpace.
- Add to `scripts/research_task_synth.py`: create task [GRAPHIFY-SIMPLEX] "Arrange J-Space centroids as regular simplex to maximize ML decoding under Gaussian noise per 2607.14087v1"
- Compute exact M*(E,ε) for current token budget 1500 vs 90000 naive → how many communities can we safely keep at ε=0.05? Use formula to set dynamic k for GraphRAG queries.
- Cross-link with MOJO (14086): SSL representations may already cluster in simplex-like arrangement (paper showed brain region classification without supervision). Check if our J-Space embeddings are close to simplex after SSL — measure pairwise cosine.

## Links

- Paper: https://arxiv.org/abs/2607.14087v1 / PDF https://arxiv.org/pdf/2607.14087v1
- Graphify source: /home/hatch/workspace/ava-research-engine/graphify_source/2607.14087v1.md
- Branch: autoresearch/jul17-graphify-rag-2607.140
- Smoke: python3 -m ava.config --preset nano --count-params OK (runner log)
- Current build: bigbang-cli/graphify-out-research/GRAPH_REPORT.md — 1120 nodes 2295 edges 102 comms, 60× reduction
- Combined context: graphify-out-research-combined 407 nodes 936 edges 31 comms (55 files)
- Previous related: 2607.14086v1 MOJO unlabelled leverage (data_starved fix), 2509.23106v1 Muon quantization, 2507.03226v2 Efficient KG Construction
- Results: results.tsv 52+ lines, be7c869 0.9979 keep

---
Expanded 2026-07-17 16:50 CDT by Scout — connects Gaussian maxima domination + Weak Simplex optimality to Graphify token pruning and J-Space simplex arrangement. Ready for 5-min smoke trial in graphify_research.py.
