# SPEC slice — Dottie pair-programming buddy (vertical)

**Status:** active (auto-mode / agent-civilization mission `dottie-pair-buddy`)
**Date:** 2026-09-07
**Tree:** `C:\Users\jcdav\dottie-main` @ clean `main`
**Team:** `feature-delivery`

## Goal

One reversible **buddy loop**: create/verify a pair against **jarvisd** as shared truth; remember/claim/goal on the daemon; platform surfaces (arxiviq conductor + optional harness-api proxy) show the same state. Unreachable jarvisd fails closed with provenance — never silent fake “paired.”

## Boundaries

| Always | Ask Cam | Never this slice |
|---|---|---|
| Loopback jarvisd source of truth | Public tunnel / production `JARVIS_URL` | Slack channel |
| Honest `demo` / `unreachable` labels | Vercel Root Directory → `apps/arxiviq` | Supabase pairings table |
| Env-gated (`JARVIS_URL` unset = prior behavior + labels) | Production bearer / Anthropic brain | Soft-archive mirrors |
| No portfolio commits unless Cam asks | Domain cutovers (slasso / arxiviq.com) | Rewrite Workers/TS daemon; flywheel promotion |

## Acceptance criteria

1. `uv run python -m jarvisd serve` on loopback; `GET /api/health` → `ok`.
2. Two agents (A then B): A `remember` + `claim` + `goal`; B sees the same via recall/claims/goals.
3. Pair create + verify against **jarvisd-backed** store; unknown/expired codes fail honestly (no “any 6-char = paired” outside explicit demo mode).
4. Conductor (or thin `/api/jarvis/*` BFF) shows live open claims/goals when jarvisd reachable; fixtures only when labeled demo/unreachable.
5. ~~Optional same-session harness-api proxy~~ — **deferred** (second public edge, no auth today); document as follow-up.
6. New/updated tests green; existing jarvisd suite still green.

## Out of scope

`host-jarvis` tunnel, phone healthcheck, Slack DoD, domain repoints, retiring COORDINATION.md fleets, Ollama-required `jarvis.ask` in CI.

## Validate gate

```powershell
cd C:\Users\jcdav\dottie-main
uv run pytest apps/jarvisd -q
uv run pytest apps/dottie-harness-api/tests -q
uv run pytest apps/scout-cli/tests -q -k pair
```

## Board

See civilization mission `dottie-pair-buddy` and parent progress board.
