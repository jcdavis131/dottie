# dottie-os curation mirror (UltraData curriculum factory + harvest/hop)

**dottie-os** is the local calibrated-decision sidecar. It lives on nugatron
under `C:\Users\jcdav\workspace\dottie-os`, and its source is backed up in the
private repo `github.com/jcdavis131/dottie-os`. **This tree is not the
sidecar.** It is the git mirror of the sidecar's curation side: the UltraData
factory, harvest and hop scripts.

What the sidecar runs on nugatron as of 2026-09-27 (its own `LIVE.md` is the
current word):

- **Advisor.** s55 (`cds-helper-bge-20260924-s55`), served by the `cds-serve`
  container on `127.0.0.1:8772` (`POST /decide`, `GET /health`). Stamped
  CHAMPION. Its `/health` says `live_gate_eligible: false`.
- **Pre-tool gate.** `sidecar/serve/gate_daemon.py` on `127.0.0.1:8774`, plus a
  user-level Claude Code PreToolUse hook (`hooks/pretool_gate.py`). It runs in
  shadow: every tool call is scored and recorded, and Claude Code's own
  permission flow runs unchanged. It stays in shadow until s55's `/health`
  says `live_gate_eligible: true`. The gate source is in the private repo.
- **`:8770` is not dottie-os.** It is the Grok Swarm's Laya lane (the
  `swarm-jev-ava` container). Dottie never calls it.
- **`:8769` (jev-ava CUDA/peft trainer) is not in this repository.** It lives
  on nugatron with the `swarm-jev-ava` stack. This tree has no `:8769` HTTP
  routes. The only HELPER FT training-start route here is
  `POST :8765/train/kickoff`.

The Dottie router's System One backend (`DOTTIE_OS_URL`, see
`docs/ROUTER.md`) is off by default, and neither the advisor nor the gate is
wired to it.

**Out of scope for this tree:** the advisor, the LIVE gate, champion files, `:8770`, and auto-promote. The HELPER FT kick (`scripts/lab/kick_helper_ft.py`) is a point-of-use integrity gate on the training host; it does not promote.

## Cam pack-pin byte spec (Swarm HQ must match byte for byte)

Shared module: `scripts/lab/cam_pin_spec.py`. Signed bytes are UTF-8:

```
swarm-hq-pin-v1\n
```

plus the JSON object with **sorted keys, no whitespace** (`json.dumps(..., separators=(",", ":"), sort_keys=True, ensure_ascii=False)`) of exactly these eight fields:

`pack_id`, `sha256_pack`, `sha256_train`, `sha256_holdout`, `rows_total`, `rows_train`, `rows_holdout`, `recordedAt`

`kid` is **not** in the signed bytes. The pin JSON also carries `cam_sig` (base64 Ed25519 signature of those bytes) and `cam_key_id`. Verify only against `apps/dottie-os/trust/cam_pin_ed25519.pub`. `stampVerified` and `pack_matches` are advisory and never sufficient.

Kicks use `swarm-hq-pin-v2` (Ed25519, `key_id`, binding `{pack_id, run_id, lease_owner}`, RFC 3339 `issued_at`/`not_before`/`not_after` with a 24 h cap and 120 s start-side skew only, nonce, sha256 pack/train/holdout). `swarm-hq-pin-v1` is verify-only history: a valid v1 signature can never authorize a kick in the child or the launcher.

HQ origin is the hardcoded `SWARM_HQ_ORIGIN` in `cam_pin_spec.py`. There is no `SWARM_HQ_URL` env, CLI, or config override. Until Cam sets the constant by PR, it is an unset placeholder that refuses. HTTPS only, certificate verification on, no proxies, no redirects. `x-agent-token` is sent only to that origin.

### Cam-side v2 signer (CLI only)

`tools/sign_cam_pin.py` is the only v2 signer. Cam runs it on his own device. It reads the Ed25519 private key from a path he passes, or from stdin (`--private-key -`). It prints `cam_sig` to stdout and never writes the key. There is no private key in this repo, in CI, in env defaults, or in test fixtures. Unittests generate ephemeral keys at runtime. Nothing in the agent or server path (`kick_helper_ft.py`, `helper_ft_kickoff.py`) calls the signer. A pin in an agent-supplied HTTP body is not provenance; only the staged v2 file the server already verified (held fd or path under `FORGE_RUN_PRIVATE_ROOT`) can authorize a kick.

Cam must turn on branch protection with **required code-owner review** on `main` for `apps/dottie-os/trust/`, `scripts/lab/cam_pin_spec.py` (the module that holds `SWARM_HQ_ORIGIN` and the shared pin-spec), `scripts/lab/kick_helper_ft.py`, the vector test helper, and `.github/workflows/ci.yml` (see `.github/CODEOWNERS`). Agents cannot set that. Runtime also refuses unless the trust key file, the pin-spec/`SWARM_HQ_ORIGIN` module, and `trust/cam_pin_key_id` match the committed HEAD blob (`git hash-object` vs `git ls-tree HEAD`). A local `git merge-base --is-ancestor HEAD origin/main` check is a **hint only**: `git update-ref` can spoof `origin/main` without a network fetch. The authoritative boundary is GitHub branch protection plus CODEOWNERS. Those blob shas and the HEAD sha are recorded in the evidence.

## Schema: strict System One records + provenance sidecar

Packs are strict `jev-decision-schema-1.0.0` records (`schema`, `id`,
`state`, `questions`, `labels`, nothing else). That is System One's frozen
contract, and `apps/jev-v0/decision_io.py` validates it. Curriculum
bookkeeping (`tier` L0-L3, `source`, `consent`, pair ids, split) goes in
`curated_pack_v2_provenance.jsonl`, keyed by id. Rows the frozen validator
refuses are dropped and counted in the summary's `schema_rejected`; they are
never repaired.

Packs written before this change used `dottie-os-decision-schema-1.0.0` with
tier/source/consent inline. `read_rows()` (and `scripts/smoke_pack_v2.py`)
still read that layout.

This is **not** `apps/dottie` (agent OS) and **not** `apps/arxiviq` (the
console app). Do not swap those trees.

## Layout

| Path | Role |
|---|---|
| `sidecar/curation/ultradata_curriculum.py` | P1 Agent / P2 Code / P3 Math curators + `curate_pack_v2` + holdout |
| `scripts/patch_hf_to_system_one.py` | Idempotent wire into nugatron `hf_to_system_one.py` (UTF-8, no BOM) |
| `scripts/smoke_pack_v2.py` | Count L3 actions / tiers / `champion=false` / holdout ≥20% |
| `scripts/apply_and_run_pack_v2.ps1` | Copy + patch + run + smoke on nugatron. No FT. |
| `scripts/lab/run_ultradata_harvest.py` | Lean harvest (agent 40 / code 40 / math 30) |
| `scripts/lab/finalize_manifest.py` | Rewrite `MANIFEST.json` to the pack-hop schema |
| `scripts/lab/cam_pin_spec.py` | Shared Cam pack-pin byte spec, Ed25519 verify, hardcoded `SWARM_HQ_ORIGIN`. CLI and `:8765` both import this module. |
| `scripts/lab/kick_helper_ft.py` | Stage-5 HELPER FT kick: verify the staged Cam-signed v2 pin (fd or path under `FORGE_RUN_PRIVATE_ROOT`; never fetch), verify Ed25519 (cofactor `[8]A != identity`, prime-order `[L]A == identity`, canonical `y < p`, `S < L`), re-hash pack/train/holdout vs that pin and MANIFEST, copy 0400 into a 0700 run dir, pass the trainer sealed memfds / held fds, write evidence, POST `:8765/train/kickoff` (never `inbox:latest`). POSTs kick and completion events to the pinned HQ origin (no redirects) except in explicit `--smoke` mode. After the trainer exits on the training host, re-hash those recorded fds into `<checkpoint>/integrity_evidence.json` (0400). `result` and `sha256_evidence` come from that file, never scraped stdout. Nonzero trainer exit/signal/timeout is `REFUSED` even when hashes match. `not_for_train:true` and leaked `state` labels refuse a real kick. Emits one `HELPER_FT_INTEGRITY_EVIDENCE` line from `kick()` only. No override, no paste path, no `SWARM_HQ_URL`. Does not call the signer. |
| `scripts/lab/helper_ft_kickoff.py` | In-repo `:8765` HELPER FT kickoff handler: verify the staged v2 pin the server already verified; never fetch; a body-only pin is not provenance. Trainer argv/config is held fds only (no source-pack fallback). Wait for the trainer in this process, then re-hash those same fds. Refuse `inbox:latest` and every other HELPER FT start route. `default_launch_trainer` refuses unless a real launcher is wired. Does not call the signer. |
| `tools/gen_cam_pin_key.py` | Cam runs on his device: write a 0600 Ed25519 private key and print the public key to commit at `trust/cam_pin_ed25519.pub`. |
| `tools/sign_cam_pin.py` | Cam-side CLI only: read private key from a path or stdin (`--private-key -`), print `cam_sig`. Never writes the key. Not called from the agent or server path. |
| `trust/cam_pin_ed25519.pub` | Committed Cam pin public key. Placeholder until Cam replaces it by PR. Missing/empty/placeholder refuses. Never read from env, argv, or another path. |
| `scripts/lab/stage-hop.ps1` | Zip jcd-pc outbox pack |
| `scripts/lab/receive-hop.ps1` | Unpack zip into nugatron trainer inbox |
| `docs/` | Pack v2 handoff, hop interface, local-exec notes |

Excluded from the root uv workspace. Hugging Face `datasets` is an optional
host extra for live harvest only — CI never downloads UltraData.

## Do not commit

- `curated_pack_*.jsonl`
- harvest tarballs / hop zips
- large datasets, `staging/`, `hop/outbox/`, `registry/`

## Stdlib smoke (this PR's verification)

```bash
python3 -m unittest discover -s apps/dottie-os/tests -v
```

No torch, no Hugging Face download, no `--go`, no GPU FT. Tests exercise
classification heuristics, holdout pairing, the pack smoke against a tiny
in-memory fixture, manifest hashing, the HELPER FT integrity gate (match,
one-byte mismatch, missing field, rewritten pack+MANIFEST, post-check swap,
symlink, missing Cam pin, mocked Swarm HQ pin fetch, split soundness, and
the real `:8765` handler via its test client), and the idempotent factory
patch.

## Host apply (nugatron only, not CI)

```powershell
$env:PACK_V2_HANDOFF = "C:\Users\jcdav\workspace\dottie-os"
powershell -ExecutionPolicy Bypass -File "$env:PACK_V2_HANDOFF\scripts\apply_and_run_pack_v2.ps1"
```

Champion / LIVE / FT stay untouched.
