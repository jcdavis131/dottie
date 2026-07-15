# Public Non-PII Graph — for jcamd.com

This sanitized graph is public-safe and published at https://jcamd.com/graphify/

- Source: graphify-out/graph.json (private, 525 nodes 1250 edges)
- Sanitized to 515 nodes 1249 edges — filtered 3 trivial 'or' nodes (concept:or duplicate fix)
- Excludes: financial balances ($), account numbers (0472, 5594, etc), emails, burn rates, EF ratios, 11k burn
- Keeps: code structure (file, function, class, module, symbol), product concepts (Turnover Shield $79-149/mo goal $1k MRR = 7-13 cust, Vector Hoops 12,966 seasons, MTNN 48→64→k, Ava AGI S1 hl8 S2 hl300, Personal Graphify), integration generics (Stripe, Plaid, Supabase, Cloudflare Workers), goal linking (first-1k-mo-passive via turnover-shield-revenue-tracker.json goal:goal_76da7701a682)
- Cost: 172950 tokens saved across 7 queries, 17.5x avg reduction, semantic toggle mxbai-embed-large Ollama-first local optional

Sanitizer: `scripts/sanitize_for_public.py` v3 deduped + or-filter — path rewrite /home/hatch -> personal-graphify/, concept ids deduped to title only, $ and @ filtered, dup check [].

Live viewer: https://jcamd.com/graphify/ + /assets/graphify/graph.json — SOTA GR-03: semantic toggle + cost tab + Task Compiler JS + Impact BFS + Onboarding god nodes, 512+ nodes loads no concept:or duplicate error, Vercel cleanUrls:true

Goal linking: references/spaces/turnover-shield-revenue-tracker.json → nodes [concept:turnover-shield, concept:mrr, concept:first-1k-mrr, concept:revenue-tracker, ecosystem:goal-first-1k] + edges tracks/enables, pricing starter $79 pro $149, target 7-13 customers $1k MRR, weekly Friday tracking trials/paid/MRR/churn%

Solo personal project, no connection to employer, built with public/free-tier only.
