# dottie-harness-api

Hostable HTTP API for the harness orchestration router. Serves two layers over
a single serverless function:

1. **Heuristic routing** — a self-contained port of the harness CLI's
   MoMA-lite classifier and graph-plan fallback
   (`apps/scout-cli/bigbang/plugins/harness/cli.py`). Always available.
2. **Learned routing** — a small MLP trained elsewhere in the repo
   (`apps/ava-factory`), executed here with numpy-only inference over vendored
   `champion_weights.json`. Available only when the weights artifact has been
   vendored; the API degrades to heuristic-only responses otherwise.

The package is fully self-contained: Vercel bundles only this directory, the
sole dependency is numpy, and the function is a stdlib
`http.server.BaseHTTPRequestHandler` subclass (no web framework).

## Endpoints

All endpoints respond `application/json`. Unknown paths return
`404 {"ok": false, "error": "not found"}`; malformed JSON bodies return 400.

### GET /api/health

```bash
curl -s https://<deployment>/api/health
```

```json
{
  "ok": true,
  "model_loaded": true,
  "model_version": "orch-mlp-v1-v4",
  "gate_passed": false,
  "corpus_stats": {"total": 829, "by_provenance": {"simulated": 815, "measured": 14}, "...": "..."}
}
```

`model_loaded: false` with null `model_version` / `gate_passed` /
`corpus_stats` means no artifacts are vendored — the service is still healthy
and serves heuristic routing.

### POST /api/route

```bash
curl -s -X POST https://<deployment>/api/route \
  -H 'Content-Type: application/json' \
  -d '{"goal": "compare stripe vs lemon squeezy pricing"}'
```

```json
{
  "ok": true,
  "goal": "compare stripe vs lemon squeezy pricing",
  "intent": "deep_research",
  "intent_scores": {"agentic_loop": 0.0, "deep_research": 3.0, "complex_action": 0.0, "deterministic": 0.0},
  "complexity": "simple",
  "moma_tier": "deep_research",
  "confidence": 0.75,
  "routed_agents": ["deep-researcher", "synthesist", "forensic-auditor"],
  "routed_count": 3,
  "learned": {"tier": "deep_research", "tier_probs": [0.0, 0.0, 0.9, 0.0, 0.1], "risk": 0.05, "cost": 1.2, "model_version": "orch-mlp-v1-v4", "gate_passed": false},
  "model_loaded": true
}
```

`learned` is `null` whenever no weights are loaded. A missing or empty `goal`
returns 400.

### POST /api/plan

```bash
curl -s -X POST https://<deployment>/api/plan \
  -H 'Content-Type: application/json' \
  -d '{"goal": "ship the harness loop"}'
```

Returns a deterministic DAG (`tierHint`, `steps[]` with
`id/idx/role/llmTier/failureRisk/sideEffect/desc`). Step risks are static
priors, and the response says so:

```json
{"risk_provenance": "static priors — no mined run history in serverless", "version": "vendored port of harness graph-plan python fallback"}
```

### GET /api/stats

```bash
curl -s https://<deployment>/api/stats
```

Returns the vendored corpus metadata (`corpus_meta`) and champion evaluation
summary (`champion` — headline metrics plus the promotion-gate verdict). Both
are `null` when nothing is vendored.

## Refreshing vendored artifacts

Artifacts are produced by the training/evaluation pipeline in
`apps/ava-factory` and copied in at build time — run before each deploy:

```bash
python lib/copy_artifacts.py
```

This vendors, when present: `champion_weights.json` (verbatim), an
`eval_summary.json` reduced to the champion + gate sections, and
`corpus_meta.json`. A missing source is reported honestly and skipped; the
package then serves `model_loaded: false`.

## Local tests

From the repo root:

```bash
uv run python -m pytest apps/dottie-harness-api/tests/test_api_local.py -q
```

Tests spin the real handler on a local `HTTPServer` and pass with or without
vendored artifacts (fixtures are injected via `DOTTIE_HARNESS_WEIGHTS` and
`DOTTIE_HARNESS_META_DIR`).

## Deploy

From this directory:

```bash
vercel deploy
```

No build step or functions config is required — the runtime auto-detects
`api/index.py` plus `requirements.txt`, and `vercel.json` rewrites
`/api/*` to the single function.

## Provenance

- **Learned outputs are never fabricated.** The `learned` block appears only
  when champion weights are actually vendored and load with full schema
  validation; otherwise responses carry `learned: null` and
  `model_loaded: false`.
- **Plan risks are static priors.** The source CLI mines per-role failure
  rates from run history; this serverless bundle has no run-history store, so
  every plan response is labeled
  `"risk_provenance": "static priors — no mined run history in serverless"`.
- **`gate_passed: false` is meaningful.** It records that the current champion
  did not beat its baselines on sufficient measured held-out data (see the
  vendored eval summary for the exact gate reason). Consumers should treat the
  learned tier as advisory and prefer the heuristic route when the two
  disagree, until a champion ships with `gate_passed: true`.
- **Corpus stats are labeled by provenance.** `corpus_stats.by_provenance`
  separates measured records from simulated battery records; headline counts
  mix both and should not be read as measured volume.
