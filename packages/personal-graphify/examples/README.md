# Personal Graphify Examples

## FastAPI (mirrors upstream demo)
```
pgraphify ~/code/fastapi --out ./graphify-out
open graphify-out/graph.html
```

## Davis Family Brain + Turnover Shield + Ava + Vector (personal)

Your home monorepo pattern:

```
01_Finance/
02_Passive_Lab/
04_Tennis_DINOv3/
ava-agi-factory-v6-4/
vector-hoops/
```

Run:

```bash
pgraphify . --out graphify-out
pgraphify query "what connects Stripe webhook to MRR"
pgraphify path "Betterment Joint" "Emergency Fund"
pgraphify explain "MTNN"
```

Measured on a self-build of this repository (48 files): 784 nodes, 2014 edges, 23
communities; example query "spectral community detection" returned a ~686-token scoped
answer vs ~83,978 naive tokens (sum of indexed file bytes / 4) = 122.4x reduction.
Your numbers depend on your corpus — every answer reports its own measured estimate.

Incremental rebuild after edits: `pgraphify . --out graphify-out --update` (reuses the
content-hash cache in `graphify-out/cache/extract.json` for unchanged files).

Solo personal project, no connection to employer, built with public/free-tier only.
