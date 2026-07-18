---
description: Personal Graphify — always query graph first before grep
globs: ["**/*"]
alwaysApply: true
---

# 🐾 Personal Graphify Rule — Query Graph First

You have `graphify-out/graph.json` built by **personal-graphify** (solo personal project, no connection to employer, built with public/free-tier only, Ollama-first).

This is NOT vector search. It's a real knowledge graph: Tree-sitter AST (code maps locally, 0 LLM cost) + semantic nodes (docs, PDFs, diagrams via Ollama) + Leiden communities + god nodes.

**Before ANY architecture / cross-file / "where is X" / "how does auth work" question:**

1. `pgraphify query "<question>"`  → returns scoped subgraph (~1.7k tokens vs ~123k naive, 71.5x reduction pattern like Karpathy corpus)
2. `pgraphify path "UserService" "DatabasePool"` → traces connection hop-by-hop with EXTRACTED vs INFERRED tags
3. `pgraphify explain "RateLimiter"` → lists incoming/outgoing edges, degree, file, community

**Check:**
- `graphify-out/GRAPH_REPORT.md` → god nodes (most-connected), surprising cross-file edges, suggested questions
- `graphify-out/graph.html` → interactive, filter by community

**Personal Ecosystem Overlay (Cameron Davis home-only):**
- Family Brain: Joint Betterment $201k + Bond $5k + Emergency $136.5k, USAA Classic $56k hub, 5 Plaid (Chase/Schwab/USAA/Betterment/Capital One), Fidelity manual Monday $1.27M incl Yubico — burn $11k/mo, EF 206%
- Passive Lab: Turnover Shield $79-149/mo, Stripe webhook → Supabase → Workers free-tier, needs 7-13 customers for $1k MRR, churn + trials tracked Friday
- Ava AGI Factory v6.4: multi_jspace_module.py S1 Fast 32 hl=8, S2 Slow 64 hl=300, Critic 16 hl=30, Planner 32 hl=150 + Router/veto, WSD 736k, YaRN 10k→1M
- Vector Hoops/Pitch/Gridiron dumbmodel.com: 12,966 player-seasons, MTNN v5_concat_b2_h160_t32_d48_mlp128 (120 feats 17 families, 544+12=556→128→48 L2), CQS 85.87, leakfree honest 0.7937
- Tennis DINOv3: ExecuTorch ConvNeXt-Tiny, ONNX WASM
- Isolation: `01_Finance / 02_Passive_Lab / 04_Tennis_DINOv3` — never `03_Meta_Work_ISOLATED`

**Secure:** Only http/https URLs, size+timeout limits, path containment, HTML-escaped labels — no SSRF/XSS.

**When to rebuild:**
- After 5+ file changes: `pgraphify . --update`
- To refresh only clustering: `pgraphify build . --cluster-only`

Never brute-grep raw files before querying graph. Graph is source of truth.
