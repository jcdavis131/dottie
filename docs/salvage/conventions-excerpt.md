# Working Conventions (salvaged patterns)

> **Salvage provenance**
> - Source repo: Blue Hen RE monorepo (`bluehenre`), github.com/jcdavis131/henington-homes
> - Source paths: `docs/wiki/SESSION_BOOT.md` (conventions), `EVIDENCE.md` (normative
>   header only), `SCIENCE_REVIEW.md` (review pattern only)
> - Source commit: `6c4cb9da0d43cb9f5379bf4ab731d597f8b47f55` (2026-08-03)
> - Copied: 2026-08-09 into dottie per `docs/CONSOLIDATION.md`
> - Edits: patterns only. Boot commands, agent registry, and lane assignments are
>   monorepo-specific and were not carried; retired-method measurement content was not
>   carried. Pending merge into `COORDINATION.md` — staged here so the source can wind down.

Three conventions from the source repo generalize beyond it and are worth carrying into
dottie's working agreements.

---

## 1. Multi-agent claim discipline (from SESSION_BOOT.md)

- **One task claimed at a time.** Check `claimedBy` in the work queue before working;
  claim before edit, release on done.
- **Classify high-stakes edits before making them:**

| Bucket | Meaning |
|---|---|
| **bucket-1** | Proceed (docs, typos, tests) |
| **bucket-2** | Sign-off required (API routes, migrations, registry files) |
| **bucket-3** | Human judgment (architecture, ML recipes, ADRs) |

- **Unattended agents are restricted to bucket-1** (bucket-2 only with an explicit
  fix-until-green test command attached).

The queue tooling that enforced this (`scripts/pick_task.py` + `config/work_queue.json`)
is salvage-listed for adaptation into dottie `scripts/` — see `docs/CONSOLIDATION.md`.

## 2. Evidence ledger discipline (from EVIDENCE.md, header pattern)

The normative rule, verbatim in spirit:

> Product claims advance only when a row moves from **Hypothesis** -> **Measured**
> (reproducible command + date) or **Rejected**. Narrative from source docs does not
> count as evidence.

Every measured row carries: the claim, its status, the measurement, and the exact
reproducible command. Retractions stay in the ledger next to what replaced them.
This is the ancestor of dottie's provenance doctrine; certification claims on the
slasso dashboard should follow it.

## 3. DROP / VERIFY review pattern (from SCIENCE_REVIEW.md)

A normative review file where:

- anything marked **DROP** must not appear in marketing, docs, or code comments;
- anything marked **VERIFY** must be checked against a primary source before it becomes
  load-bearing.

Reusable as an integrity gate for dashboard and marketing copy: run new public-facing
claims through a DROP/VERIFY pass before they ship.
