# Blue Hen RE Glossary (salvaged decoder ring)

> **Salvage provenance**
> - Source repo: Blue Hen RE monorepo (`bluehenre`), github.com/jcdavis131/henington-homes
> - Source path: `memory/glossary.md` (127 lines)
> - Source commit: `6c4cb9da0d43cb9f5379bf4ab731d597f8b47f55` (2026-08-03)
> - Copied: 2026-08-09 into dottie per `docs/CONSOLIDATION.md`
> - Edits: retired-method-era terms removed (the ASN training method and its derived
>   nicknames — collapse shorthand, baseline-leaderboard and mascot nicknames, the
>   whitepaper), along with agent-tooling rows tied to the retired monorepo workflow.
>   Everything kept below is the vocabulary needed to read the other salvaged artifacts.
>   Paths refer to the deprecated monorepo unless marked otherwise.

## Acronyms

| Term | Meaning | Context |
|------|---------|---------|
| **RE** | Relay Engine · RAG Embeddings | Dual brand — pair in public copy |
| **SDD** | Spec-Driven Development | Monorepo agent coding rules |
| **RLS** | Row-Level Security | Postgres tenant isolation (Spec 0002) |
| **BD** | Validation & Charter division | Benchmark certification leg |
| **RAG** | Retrieval-Augmented Generation | Product domain |
| **nDCG@10** | Normalized DCG at 10 | Primary retrieval eval metric |
| **MRL** | Matryoshka Representation Learning | Truncation / edge serving tiers |
| **BFF** | Backend-for-frontend | Next.js `/api/*` routes hold the API key |
| **P0/P1/P2/P3** | Priority levels | P0 = prod ship blocker |

## Internal terms

| Term | Meaning |
|------|---------|
| **Lifecycle Run** | Hill-climb: collect -> train -> deploy -> index |
| **Operations Ledger** | Experiment ledger (`auto_research_ledger`) |
| **Live Search** | Retrieval UI on any product surface |
| **Operations Feedback** | Feedback form -> ledger |
| **Validation Queue** | BD promotion queue (`content/fleet/bd/queue.json`) |
| **Research Registry** | Method museum (research-lab page) |
| **Evidence Rows** | Rows in the evidence ledger (EVIDENCE.md pattern) |
| **Production Model** | Currently deployed org embedding model |
| **Cost Budget** | Per-workspace daily cost ceiling |
| **deploy** | Deploy model + index to pgvector (Production leg) |
| **eval gate** | Metric threshold in eval-harness before deploy (Spec 0008) |

## Names

| Name | Meaning |
|------|---------|
| **Operator** | Human repo owner (jcdavis131) |
| **Eve** | Fleet Director synthetic agent (retired with the monorepo) |

## Project codenames

| Codename | Also called | Project |
|----------|-------------|---------|
| **bluehenre** | blue hen re folder | Monorepo / platform root (deprecated) |
| **SynthaEmbed OS** | synthaembed | Internal platform name (deprecated) |
| **Storefront** | bhenre, hub | bhenre.com tenant dashboard (retired surface) |
| **Headquarters** | jcamd, control | Operator plane (jcamd.com repurposed 2026-07-04) |
| **Validation Lab** | slasso, benchmark-lab, agent-lasso | slasso.com RAG benchmarks (stays live) |
| **Applied Research** | arxiviq, research-rag, arxiv exam | arxiviq.com research RAG (stays live) |
| **Baseline Comparison** | dumbmodel | dumbmodel.com public proof (stays live) |
| **Simulation Lab** | simulation, finance org | Paper trading (retired with bhenre.com) |
| **Operating Loop** | closed loop | Five-division handoff cycle (Spec 0012) |

## Domain aliases

| Shorthand | Domain | Site id |
|-----------|--------|---------|
| bhenre | bhenre.com | storefront (retired) |
| jcamd | jcamd.com | hq (domain repurposed) |
| slasso | slasso.com | validation |
| arxiviq | arxiviq.com | research |
| dumbmodel | dumbmodel.com | dumbmodel |

## Operating Loop divisions

| Surface name | Division id | Handoff |
|--------------|-------------|---------|
| Platform Orchestration | orchestration | priorities & budgets |
| Data Operations | data | curated corpora |
| Research & Development | research | recipes & evidence |
| Validation & Charter | bd | production charter |
| Production | execution | live serving metrics |

## Operations Ledger stage decoder

| Stage | Label | Division |
|-------|-------|----------|
| collect | ingest | Data Operations |
| chunk | chunk | Data Operations |
| pairs | pair build | Data Operations |
| train | train | R&D |
| eval | evaluate | R&D |
| pilot | validation pilot | Validation |
| charter | production charter | Validation |
| deploy | deploy | Production |
| index | index | Production |
| feedback | operations feedback | all |

## Spec shorthand (source-repo spec numbers cited by salvaged artifacts)

| Ref | Topic |
|-----|-------|
| 0002 | Tenancy + RLS |
| 0007 | Fleet registry |
| 0008 | Eval gates + BD queue (salvaged: `spec-0008-eval-harness-and-gates.md`) |
| 0012 | Org divisions + closed loop (salvaged: `spec-0012-operating-loop-excerpts.md`) |
