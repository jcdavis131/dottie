# Dottie platform readiness — 2026-09-07

**Baseline:** local `main` and `origin/main` both resolve to
`71dabf3bc692cc909465c00a69b3e8456d19f5c3` (`71dabf3`)
**Change state:** reviewed implementation; not deployed
**Verdict:** **NOT RELEASE READY — external requirements remain**
**Agent-solvable status:** no remaining known agent-solvable blocker after the
latest implementation and review pass. The code reviewer **APPROVED** with no
P0/P1 agent-solvable findings.

Only runs that crossed real process, storage, model, and browser boundaries are
listed as E2E. Deterministic tests, static checks, and builds are kept separate.

## REAL E2E

- **Dottie + real local model:** the existing Ollama `qwen3:8b` served a real
  request through Dottie. The result identified the Ollama backend and did not
  promote an open-ended response into a synthetic task score.
- **Real pairing and state:** a fresh jarvisd process, fresh SQLite database,
  arxiviq Next BFF, and browser created and verified a real expiring pair code.
  The authenticated browser session then read the fixed configured repository's
  real claims and goals; no browser-local or in-memory pair/state fallback was
  accepted as evidence.
- **Security boundary:** the live path failed closed for SSRF, including the
  metadata target; pair rate limiting was isolated by trusted per-client identity;
  and successful pairing used a short-lived signed session. Public client
  identity is derived only from a platform-trusted header and is HMAC
  pseudonymized before central rate keys or jarvis agent IDs are created.
- **Real conductor slice:** browser actions traversed the arxiviq BFF to jarvisd
  for `feedback.push`, `scratchpad.write`, `todo.create`, and `todo.move`.
  Feedback, scratchpad, and todo state persisted across a jarvisd daemon restart.
  The conductor data disappeared when jarvisd was stopped, proving that the UI
  did not retain or invent daemon state during outage.
- **Focused keyboard/accessibility audit:** keyboard traversal, visible focus,
  control semantics, status/error announcement behavior, and disabled/unavailable
  states were exercised on the changed browser surfaces. This is a focused audit,
  not a claim of a complete independent WCAG certification.

## UNIT / BUILD

These are the latest completed gate results for the current uncommitted change,
not substitutes for the real E2E evidence above:

- jarvisd: **88 passed, 1 skipped** in the broad suite. After the final app
  trimming change, the focused snapshot coverage was **4 passed, 12 deselected**;
  this focused result is the final post-trim evidence.
- dottie-harness-api: **83 passed** (latest API run).
- arxiviq: **37 passed** under Node (latest); lint, typecheck, production build,
  and production dependency audit all exited clean with **0 audit findings**.
- Ava final safe no-Torch suite (`test_reproducibility_integrity.py`,
  `test_manifest.py`, `test_distill_ladder.py`): **90 passed**. The earlier
  broader **158 passed** result is historical pre-final-retirement evidence and
  is not current. No train/evaluate/serve claim follows from the final suite.
- Scout/portability affected suites: **48 passed, 1 skipped**. The full Scout
  result **2571 passed, 2 skipped** is historical context only and was not rerun
  after the final slice.
- Docker static contract: **66 passed**. This proves configuration/package/
  least-privilege contracts, not an image build or running-container smoke.
- Any other package counts from earlier review iterations are historical only and
  are intentionally not presented as current release gates.

## Fixed blockers

- **Frontend:** migrated to Next `16.3.4` and React `19.2.8`; lint, typecheck,
  build, and `npm audit` are clean.
- **Pair/session security:** pair success now derives an authenticated session;
  public rates use trusted, per-client, pseudonymous central identities rather
  than caller-controlled forwarding data.
- **Harness API:** production entrypoints fail closed without authentication and
  complete deployment policy; reachable output is request-derived and explicitly
  non-learned, while synthetic corpus/model/analytics output is unavailable.
- **Conductor:** the product path is a real jarvisd-backed, bounded read/write
  slice with exact RPC allowlisting and persisted SQLite state.
- **Ava:** source provenance, license policy, content hashes, manifest integrity,
  and safe checkpoint/tokenizer loading are enforced before use.
  `on_policy_distill` is intentionally retired fail-closed before any
  model/data/artifact access until the canonical config/manifest sampler is
  ported and the external tokenizer, data, and hardware gates clear.
- **Containers:** pre-runtime configuration, package closure, secret/context
  exclusions, non-root execution, dropped capabilities, read-only root
  filesystem, bounded writable volumes, and healthcheck contracts are covered.

## External-only release requirements

1. **`EXT-TOKENIZERS`: dependency auditor BLOCK.** CVE-2026-85670 affects
   `tokenizers <=0.23.2`, and no patched release exists as of 2026-09-07. Do not
   run tokenizer/curator code, Torch, an Ava image, training, serving, or
   evaluation until a patched version is available, audited, and pinned in every
   manifest.
2. **`EXT-AVA-ASSETS`: real model lineage.** After `EXT-TOKENIZERS` clears,
   obtain verified 40-hex source revisions and licenses plus actual licensed
   dataset bytes; produce a lineage-v1 checkpoint and matching tokenizer; provide
   adequate RAM and free GPU capacity; port the canonical distillation
   config/manifest sampler; then run the real train → evaluate → serve chain.
   This port remains external/product scope now because its execution and data
   prerequisites are unavailable; the legacy unsafe route has been removed.
3. **`EXT-DOCKER-RUNTIME`: operator runtime.** Docker Desktop is stopped. Low
   available RAM and an active GPU workload made starting it unsafe. After that
   workload ends, an operator must start Docker Desktop and run build, up,
   health, auth, restart-persistence, and read-only-filesystem smokes.
4. **`EXT-HARNESS-EDGE`: public deployment ownership.** Name the deployment
   owner; provide the actual distributed edge policy ID/configuration; document
   bearer rotation and revocation; and smoke the canonical HTTPS host with
   request-verified platform metadata. The code remains not ready for public
   deployment without that independently verified policy.
5. **`EXT-ARXIVIQ-PROD`: production topology.** Provision production secrets and
   environment variables and make the approved jarvisd topology reachable.
   Local E2E is proven; production reachability is not.
6. **`EXT-PRODUCT-SCOPE`: intentional capability boundary.** Command execution,
   PTY, tunnels, remote-machine/session control, and guardrail mutation are
   intentionally unsupported and are not claimed. Any expansion requires Cam's
   explicit safety and product decision.

## Exact verification commands

Run from PowerShell. Each command must exit `0`; do not pipe a gate whose exit
code is being evaluated.

```powershell
Set-Location C:\Users\jcdav\dottie-main
git rev-parse HEAD
git rev-parse origin/main
uv run pytest apps/jarvisd -q
uv run python -m pytest apps/dottie-harness-api/tests/test_api_local.py -q
Push-Location apps\ava-factory
uv run python -m pytest tests/test_reproducibility_integrity.py tests/test_manifest.py tests/test_distill_ladder.py -q
Pop-Location
uv run python -m pytest apps/scout-cli/tests/test_harness_correct.py apps/scout-cli/tests/test_harness_vector.py apps/scout-cli/tests/test_inbox_focused.py apps/scout-cli/tests/test_infer_focused.py apps/scout-cli/tests/test_secrets_focused.py packages/ava-open-harness/tests/test_dottie_assistant.py -q
uv run --no-sync python scripts/test_dottie_container_contract.py
Set-Location apps\arxiviq
npm test
npm run lint
npm run typecheck
npm run build
npm audit --omit=dev --audit-level=high
```

After `EXT-DOCKER-RUNTIME` is cleared:

```powershell
Set-Location C:\Users\jcdav\dottie-main
$env:JARVIS_BEARER = python -c "import secrets; print(secrets.token_urlsafe(32))"
docker compose -f docker-compose.dottie.yml config
docker compose -f docker-compose.dottie.yml build jarvisd
docker compose -f docker-compose.dottie.yml up -d jarvisd
curl.exe --fail --silent http://127.0.0.1:8790/api/health
curl.exe --fail --silent -H "Authorization: Bearer $env:JARVIS_BEARER" http://127.0.0.1:8790/api/claims
docker compose -f docker-compose.dottie.yml restart jarvisd
curl.exe --fail --silent -H "Authorization: Bearer $env:JARVIS_BEARER" http://127.0.0.1:8790/api/claims
docker compose -f docker-compose.dottie.yml exec jarvisd sh -c "test ! -w / && test -w /data && test -w /workspace"
docker compose -f docker-compose.dottie.yml down
```

Public harness and arxiviq smoke commands are intentionally withheld until the
operator supplies approved canonical hosts and deployment policy; substituting a
loopback or caller-forged forwarding header would not verify the required edge.

## Board and readiness

- `b1`–`b8`: **completed**
- `b7`: **approved / completed** — code reviewer APPROVED with no P0/P1
  agent-solvable findings
- `b8`: **docs current / completed**
- `b9`: **final verification completed**

Reviewer iterations caught and corrected `ignoreBuildErrors`, unsafe legacy
distillation lineage, randomness, malformed labels, config/data identity gaps,
feedback ordering/cap behavior, and stale root README learned/deployed claims.
The distillation path was retired truthfully fail-closed instead of being
replaced with a fake implementation.

The handoff is reviewed and verified, but the product is **NOT RELEASE READY**.
Release remains stopped only on the external requirements above.

## Deliberate non-actions

- No commit, push, deploy, production configuration, secret provisioning, Docker
  daemon start, or paid API use.
- No tokenizer/curator/Torch/Ava image/training/serve/eval execution while
  `EXT-TOKENIZERS` is blocked.
- No synthetic dataset, mock checkpoint, canned model output, caller-forged edge
  metadata, browser-local daemon, or in-memory persistence was promoted as E2E.
- No command/PTY/tunnel/remote-machine/guardrail capability was added or claimed.
