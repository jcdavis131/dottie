# Public Non-PII Graph — for jcamd.com

This sanitized graph is public-safe and published at https://jcamd.com/graphify/

- Source: graphify-out/graph.json (private, 391 nodes 736 edges)
- Sanitized to 390 nodes 735 edges
- Excludes: financial balances ($), account numbers (0472, 5594, etc), emails, burn rates, EF ratios, 11k burn
- Keeps: code structure (file, function, class, module, symbol), product concepts (Turnover Shield, Vector Hoops, MTNN, Ava AGI, Personal Graphify), integration generics (Stripe, Plaid, Supabase, Cloudflare Workers)

Sanitizer: `scripts/sanitize_for_public.py` (path rewrite /home/hatch -> personal-graphify/, concept ids deduped to title only, $ and @ filtered)

Live viewer: https://jcamd.com/graphify/ + /assets/graphify/graph.json

Solo personal project, no connection to employer, built with public/free-tier only.
