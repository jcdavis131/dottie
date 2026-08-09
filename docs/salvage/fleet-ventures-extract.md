# fleet.json Venture Definitions (salvaged extract)

> **Salvage provenance**
> - Source repo: Blue Hen RE monorepo (`bluehenre`), github.com/jcdavis131/henington-homes
> - Source path: `config/fleet.json` (validation block lines 164-201; dumbmodel lines
>   129-163; research lines 202-242)
> - Source commit: `6c4cb9da0d43cb9f5379bf4ab731d597f8b47f55` (2026-08-03)
> - Copied: 2026-08-09 into dottie per `docs/CONSOLIDATION.md`
> - Edits: extract only — the three venture blocks for the surviving sites, JSON verbatim.
>   Deprecated-site blocks (storefront, simulation, refinery, observatory, hq) not carried;
>   see `docs/CONSOLIDATION.md` for their disposition.

**Why salvaged:** the `validation` block is the slasso.com dashboard's product framing
verbatim — value proposition, CTA, and the normative data-consent line. The `dumbmodel`
block cross-references certification via slasso.com, confirming the public funnel.

---

## validation (slasso.com) — the dashboard's product framing

```json
{
  "id": "validation",
  "name": "Validation Lab",
  "domain": "slasso.com",
  "phase": "A",
  "role": "rag-benchmark",
  "orgDivision": "bd",
  "secondaryDivisions": ["research"],
  "deliversTo": ["execution", "research", "orchestration"],
  "expectsFrom": ["research", "execution", "data"],
  "appPath": "apps/sites/validation",
  "package": "@synthaembed/validation",
  "port": 3003,
  "vercelPreview": null,
  "status": "active",
  "legacyRepo": "agent-lasso",
  "description": "Validation Lab - paid RAG certification with published scorecards and the promotion queue.",
  "venture": {
    "valueProp": "RAG certification - paid reproducible benchmark runs with published scorecards",
    "cta": { "label": "Get your RAG certified", "href": "/certify" },
    "monetization": "RAG Certification Run product (store, USD placeholder pending Operator pricing)",
    "dataConsent": "Customer eval sets under NDA; published scorecards only with clearance"
  },
  "orgRole": "business-unit"
}
```

The `dataConsent` line is normative for the dashboard: customer eval sets stay under NDA;
scorecards publish only with clearance.

## dumbmodel (dumbmodel.com) — funnel cross-reference

```json
{
  "id": "dumbmodel",
  "name": "Dumb Model",
  "domain": "dumbmodel.com",
  "phase": "A",
  "role": "public-proof",
  "orgDivision": "bd",
  "secondaryDivisions": ["research"],
  "deliversTo": ["orchestration"],
  "expectsFrom": ["research", "bd", "execution"],
  "appPath": "apps/sites/dumbmodel",
  "package": "@synthaembed/dumbmodel",
  "port": 3001,
  "vercelPreview": null,
  "status": "active",
  "legacyRepo": null,
  "description": "The arcade — Blind Rank, Beat the Baseline, and measured embedding proof tools.",
  "venture": {
    "valueProp": "Rank anything blind — eight picks, tier list reveal, real rank engine underneath",
    "cta": { "label": "Start blind rank", "href": "/arena" },
    "monetization": "Evaluation Credits via bhenre.com/store; certification via slasso.com",
    "dataConsent": "Arena picks stored anonymously per session (sessionStorage userRef); /check opt-in → data/datalab/inbox"
  },
  "orgRole": "business-unit"
}
```

Note: the `monetization` field's bhenre.com store reference is retired with that surface;
the "certification via slasso.com" cross-reference is the part that carries.

## research (arxiviq.com)

```json
{
  "id": "research",
  "name": "Applied Research",
  "domain": "arxiviq.com",
  "phase": "A",
  "role": "research-rag",
  "orgDivision": "research",
  "secondaryDivisions": ["data", "bd", "execution"],
  "deliversTo": ["bd", "orchestration", "data"],
  "expectsFrom": ["data", "bd", "execution", "orchestration"],
  "appPath": "apps/sites/research",
  "package": "@synthaembed/research",
  "port": 3004,
  "vercelPreview": null,
  "status": "active",
  "legacyRepo": "arxiv_exam_app",
  "description": "Applied Research - live arXiv retrieval assistant and research method registry.",
  "venture": {
    "valueProp": "Research retrieval assistant over arXiv - the live demo is the product",
    "cta": { "label": "Reserve a design-partner seat", "href": "https://bhenre.com/store" },
    "monetization": "Design Partner Seat (store); usage-metered API later",
    "dataConsent": "Query logging deferred until consent UI ships (Spec 0015 gate)"
  },
  "orgRole": "business-unit"
}
```

Note: the CTA points at the retired bhenre.com store and needs a new destination when
arxiviq copy is next touched; the `dataConsent` deferral stands until a consent UI ships.
