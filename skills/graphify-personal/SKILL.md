---
name: graphify-personal
description: Personal overlay for Cameron Davis home ecosystem — Family Brain, Passive Lab, Ava AGI Factory, Vector Hoops
triggers:
- family brain
- turnover shield
- mtnn
- ava j-space
- davis family
- passive lab
- vector hoops
- tennis dinov3
version: 1.0.0
dependencies:
- graphify-core
provider: ollama
---

# Graphify Personal — Home Ecosystem Overlay

Solo personal project, no connection to employer, built with public/free-tier only.

Personal layer on top of graphify-core, tailored to `/01_Finance /02_Passive_Lab /04_Tennis_DINOv3` isolation (never `03_Meta_Work_ISOLATED`).

## Home Patterns Detected

The extractor looks for these and creates dedicated nodes:

- **Family Brain**: Betterment buckets (Joint $201,954 Automated 5594 + Bond $5,039 + Emergency $136,500 + Cash $27,760), USAA Classic 0472 $56k hub (7 accounts), Schwab 8889 $536k META 379 @ $669 + VOO + NVDA, Plaid 5 institutions live, Fidelity manual Monday 9am CT $1.27M incl Yubico, burn $11k/mo, EF 12.4mo 206%
- **Turnover Shield**: Trade Crew Turnover Shield $79 Pro / $149 Pro, Stripe checkout → Supabase pg → Cloudflare Workers free-tier, MRR target $1k = 7-13 customers, weekly Friday fields: trials / paid_users / MRR / churn_pct / notes, ROI pitch "saving 1 tech = $5k hiring cost", 60% code reuse across top 3 ideas
- **Ava AGI Factory v6.4**: `multi_jspace_module.py` 4 workspaces S1 Fast 32 hl=8 / S2 Slow 64 hl=300 / Critic 16 hl=30 / Planner 32 hl=150 + Router/veto, YaRN 10k→1M NTK-aware QK-Norm, WSD 736k 92% stable, branching eval 100% cap preservation, Docker pytorch:2.4.0-cuda12.4-cudnn9
- **Vector Hoops**: 12,966 player-seasons, MTNN v5_concat_b2_h160_t32_d48_mlp128, 120 feats 17 families cat([x·m,m]), 17x towers 160→32 + season_emb 12 =556→128→48 L2-norm, CQS 85.87 leakfree 0.7937 composite (0.977 recall@10 / 0.6717 purity@20), 8 archetypes, homepage NBA Cities Three.js
- **Tennis DINOv3**: ExecuTorch distilled ConvNeXt-Tiny/Small XNNPACK-friendly, ONNX WASM 2MB, DINOv3 serve coach

## Query Examples
- `pgraphify query "where is turnover retention playbook?"`
- `pgraphify query "trace Stripe webhook to MRR dashboard"`
- `pgraphify query "Ava S2 Slow vs Planner broadcast"`
- `pgraphify query "MTNN head 48→64→k archetype"`
- `pgraphify path "Betterment Joint" "Emergency Fund"`

## God Nodes in Personal Repo (expected)
- `PROJECT.md`, `Turnover Shield Stripe webhook`, `S2 Slow hl300`, `MTNN head`, `Family Brain Plaid hub`

Use surprises to find unwanted coupling: e.g., Family Brain ↔ Turnover Shield sharing same parser = risk.

Solo personal project, no connection to employer, built with public/free-tier only.
