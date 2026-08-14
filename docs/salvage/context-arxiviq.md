# Applied Research (arxiviq) — site context (salvaged)

> **Salvage provenance**
> - Source repo: Blue Hen RE monorepo (`bluehenre`), github.com/jcdavis131/henington-homes
> - Source path: `memory/projects/arxiviq.md`
> - Source commit: `6c4cb9da0d43cb9f5379bf4ab731d597f8b47f55` (2026-08-03)
> - Copied: 2026-08-09 into dottie per `docs/CONSOLIDATION.md`
> - Edits: near-verbatim.

**Codename:** arxiviq, Applied Research, research-rag
**Also called:** "arxiv exam app" (legacy repo)
**Domain:** arxiviq.com
**Status:** Active — stays live, untouched by the consolidation
**Site id:** `research`

## What it is

R&D product surface — arXiv-flavored RAG evaluation, Research Registry (method museum),
live search on org corpus.

## Key roles

- **Research & Development** — primary division
- **Data Operations** — corpus ingest secondary
- **Validation & Charter** — receives promotion candidates

## Context

- `/research-lab` — Research Registry (`data/research_lab.json`)
- `/` — live search + arXiv exam demo
- The research-lab page is a registry snapshot, not a live sweep view

## Tech (as deployed from the source repo)

- App: `apps/sites/research` (Vercel project "arxiv-exam-app")
- Workspace key: `data/workspaces/research-rag.env`
- Local port: 3004
