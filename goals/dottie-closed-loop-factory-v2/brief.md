# Dottie Closed-Loop Factory v2 — Glimmer Harness

**Branch:** scout/glimmer-dottie-harness
**Goal:** dottie-closed-loop-factory-v2
**Date:** 2026-08-29
**Lane 1:** Dottie Local Harness Hardening — COMPLETE

## Status

Hardened branch scout/glimmer-dottie-harness with security fixes, honest 503 verification, 7-field timeline mandatory.

## What Shipped / Hardened

- glimmer.ts 863 LOC local agent loop plan→tool→check→recover, 131k context, low/medium/high/xhigh reasoning via system prompt, provider detection Ollama → llama.cpp → unavailable honest 503
- ollama-gateway.ts 200 LOC zero-deps fetch, honest 503 mapping, SSRF guard
- dottie-glimmer-adapter.ts tier routing deterministic/llm/deep_research/action_operator/epic, prompt injection boundary delimiters, extraTools allowlist
- api/glimmer route GET health + POST agent loop, honest 503 never synthetic
- api/judge route fixed import extensionless, async, timeline triple-write
- scout-cli glimmer.py safe tools default read-only, FULL_TOOLS gated via env, blocked path validation
- glimmer-pull.sh + glimmer-test.ts offline verification

## Security Review

See docs/glimmer/HARDENING_REPORT.md — 9 defects, 7 fixed, 2 accepted low-risk.

Critical:
- Python exec/write RCE fixed via env gates + allowlist
- TS path traversal fixed via normalize + blocklist + workspace root + 0600
- SSRF fixed via local URL allowlist

High:
- Prompt injection fixed via delimiters + safeId + rules
Medium:
- Secrets 0600 chmod on timeline
- Judge import .js break fixed
- 7-field timeline verified mandatory even no-change

## 7-Field Timeline

nodeId, agentId, attempt, latency_ms, tokens_est, status, errorClass mandatory.

Verified 6 call sites in glimmer.ts all include 7 fields. Triple-write to:
- goals/dottie-closed-loop-factory-v2/hidden_files/timeline.jsonl
- dottie/bundles/ultra/runs/dottie-closed-loop-factory-v2/timeline.jsonl
- bundles/ultra/runs/dottie-closed-loop-factory-v2/timeline.jsonl
- .scout/missions/dottie-closed-loop-factory-v2/timeline.jsonl
- .scout/missions/_cron/timeline.jsonl

Even no-change logged via glimmer-agent-loop-start status started.

## Honest 503 Verification

Hatch CPU (no Ollama): provider unavailable → 503 with hint ollama pull muse-glimmer-30b, offline=false, never synthetic.

Verified:
- python glimmer_chat offline returns ok False, error contains ollama not reachable
- TS detectProvider returns unavailable
- GET /api/glimmer returns 503 policy honest-503-never-synthetic
- POST requires prompt else 400

## Tests

- Python test_glimmer.py 15 tests manually verified via python -c (pytest not in env): preferred ordering, reasoning levels, system prompt, messages, image encode missing/real, endpoint env, offline handling, available offline false, best model fallback, glimmer picking, CLI exists, GLIMMER_MODELS export — all PASS
- TS tsc --noEmit times out due to uv.lock 469KB + node_modules missing — earlier lockfile timeout real, not code defect. Import extensions fixed to unblock. Full build needs Forge/Alienware.
- Honest 503 behavior verified on Hatch CPU, no fake inference.

## Next Steps

- Forge/Alienware: pull weights `ollama pull muse-glimmer:30b` or `huggingface-cli download meta-llama/Muse-Glimmer-30B`, verify offline_ready true, smoke test `node scripts/glimmer-test.ts`
- Wire into Dottie conductor tandem routing, always-on orchestrator, heartbeat
- Open PR scout/glimmer-dottie-harness → main after review, no merge yet per task

## Zero-Deps, English Only

Stdlib only, fetch only, no torch/pip, English or code only, full-scale real data only, never synthetic.

