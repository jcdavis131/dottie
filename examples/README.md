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

Expected: 400-600 nodes, 15-20% reduction vs naive scanning, god nodes like PROJECT.md.

Solo personal project, no connection to employer, built with public/free-tier only.
