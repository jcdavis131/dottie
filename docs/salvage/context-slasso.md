# Validation Lab (slasso) — site context (salvaged)

> **Salvage provenance**
> - Source repo: Blue Hen RE monorepo (`bluehenre`), github.com/jcdavis131/henington-homes
> - Source path: `memory/projects/slasso.md`
> - Source commit: `6c4cb9da0d43cb9f5379bf4ab731d597f8b47f55` (2026-08-03)
> - Copied: 2026-08-09 into dottie per `docs/CONSOLIDATION.md`
> - Edits: near-verbatim; bracketed notes mark items retired with the monorepo.

**Codename:** slasso, Validation Lab, benchmark-lab
**Also called:** "agent-lasso" (legacy repo; also the Vercel project name)
**Domain:** slasso.com
**Status:** Active — stays live; destination of the training-progress dashboard
**Site id:** `validation`

## What it is

Validation & Charter product surface — certified RAG benchmark exams, leaderboards,
promotion pipeline UI. Silver Lasso lineage.

## Key roles

- **Validation & Charter (BD division)** — owns exam gates and the Validation Queue
- **Operator** — pilot approval
- **Research & Development** — submits candidates to the queue

## Context

- `/try` — run benchmark (live search)
- `/queue` — Validation Queue (`data/bd/queue.json` in the site app; canonical source
  `content/fleet/bd/queue.json` — salvaged as `docs/salvage/bd-queue.json`)
- YAML exam runner — was a Phase A TODO in the source repo
- Public funnel: dumbmodel (baseline) -> slasso (validation) -> console
  [note: the bhenre.com console endpoint of the funnel is retired; successor console TBD]

## Tech (as deployed from the source repo)

- App: `apps/sites/validation` (Vercel project "agent-lasso")
- Workspace key: `data/workspaces/benchmark-lab.env`
- Local port: 3003
