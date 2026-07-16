# Personal Ecosystem Project Map

Solo personal project, no connection to employer, built with public/free-tier only.

This overlay links Ava, Scout, Vector lab games, Turnover Shield, Family Brain, and Personal Graphify so agents can query cross-repo structure.

## Control plane

- **Scout CLI** (ex-BigBang) — agent-native personal control plane: Ava brain routing, authentic writing, lab MRR tracking, RTX offload. HOME-only.
- **Personal Graphify** (`pgraphify`) — query-first knowledge graph; task compiler + impact + onboard + MCP. Public demo at jcamd.com/graphify/.

## Ava AGI Factory v6.4

- Real-mode Jacobian multi-space: S1 Fast hl8, S2 Slow hl300, Critic hl30, Planner hl150, Router/veto.
- WSD 736k, YaRN 10k→1M, local Docker CUDA, Ollama qwen3:32b judge.
- Scout CLI orchestrates Ava for HOME workflows; Personal Graphify maps J-space interactions for agents.

## Vector / dumbmodel.com lab

- **Vector Hoops** — 12,966 player-seasons, MTNN v5, CQS 85.87, hoops.dumbmodel.com
- **Vector Pitch** — 633 WC tournaments, pitch.dumbmodel.com
- **Vector Gridiron** — fantasy MTNN MAE 4.268, gridiron.dumbmodel.com
- **Tennis DINOv3** — ExecuTorch ConvNeXt serve coach

## Passive Lab / goals

- **Turnover Shield** — B2B SaaS churn prediction $79–149/mo, goal first $1k/mo MRR (7–13 customers), Stripe → Supabase → Workers.
- Scout tracks lab MRR; Graphify goal_76da7701 links revenue tracker → first-1k-mrr.

## Hub

- **jcamd.com** — workforce intelligence consulting site + Lab cards + public non-PII Graphify viewer.

## Agent recipes

```
pgraphify query "how does Scout connect to Ava?"
pgraphify path "Scout CLI" "Ava Planner hl150"
pgraphify task "wire Scout control plane to Ava J-space router"
pgraphify impact "multi_jspace" --direction both
```
