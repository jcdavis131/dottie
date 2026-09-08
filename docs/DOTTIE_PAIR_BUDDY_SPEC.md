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
| jarvisd source of truth; explicit exact HTTPS production origin | Public tunnel provisioning | Slack channel |
| Fail-closed `unreachable` / configuration provenance | Vercel Root Directory → `apps/arxiviq` | Supabase pairings table |
| `JARVIS_URL` required for pairing | Production bearer / Anthropic brain | Soft-archive mirrors |
| No portfolio commits unless Cam asks | Domain cutovers (slasso / arxiviq.com) | Rewrite Workers/TS daemon; flywheel promotion |

## Acceptance criteria

1. `uv run python -m jarvisd serve` on loopback; `GET /api/health` → `ok`.
2. Two agents (A then B): A `remember` + `claim` + `goal`; B sees the same via recall/claims/goals.
3. Pair create + verify against **jarvisd-backed** store; unknown/expired codes fail honestly and no “any 6-char = paired” path exists.
4. Pair verification atomically consumes a code once and creates a signed,
   pseudonymous, fixed-repo session lasting no longer than the pair code or 600
   seconds. Newly minted sessions carry `conductor:read`/`conductor:write`;
   older cookies are intentionally invalid. Claims/goals are GET-only, while the
   same-origin conductor BFF exposes snapshot plus the exact feedback, scratchpad,
   and todo write allowlist. Pair and conductor mutation bodies are stream-bounded,
   including chunked requests without `Content-Length`. All reject missing/invalid
   sessions. The edge accepts client IP only from Vercel metadata or an
   explicitly configured platform-overwritten header, HMAC-pseudonymizes it,
   and uses the same stable identity for edge and jarvisd buckets. Exact
   loopback HTTP operation uses a fixed local-only identity.
5. ~~Optional same-session harness-api proxy~~ — **deferred** (second public edge, no auth today); document as follow-up.
6. New/updated tests green; existing jarvisd suite still green.

## Out of scope

`host-jarvis` tunnel, phone healthcheck, Slack DoD, domain repoints, retiring COORDINATION.md fleets, Ollama-required `jarvis.ask` in CI.

## Validate gate

```powershell
cd C:\Users\jcdav\dottie-main
uv run pytest apps/jarvisd -q
uv run pytest apps/scout-cli/tests -q -k pair
cd apps/arxiviq
npm test
npm run test:e2e
npm run typecheck
npm run lint
npm run build
```

## Board

See civilization mission `dottie-pair-buddy` and parent progress board.
