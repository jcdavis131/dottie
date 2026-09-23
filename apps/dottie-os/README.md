# dottie-os — UltraData curriculum factory + harvest/hop (repo mirror)

Local System One sidecar lives on nugatron under
`C:\Users\jcdav\workspace\dottie-os`. This tree is the git mirror for the
UltraData factory, harvest, and hop scripts.

**Out of scope for this tree / this PR:** champion serve `:8770`, the LIVE
gate, and any FT kick. LIVE gate source exists only on offline nugatron disk
and is a blocked follow-up.

This is **not** `apps/dottie` (agent OS) and **not** `apps/arxiviq` (System One
copy already on main via #52). Do not swap those trees.

## Layout

| Path | Role |
|---|---|
| `sidecar/curation/ultradata_curriculum.py` | P1 Agent / P2 Code / P3 Math curators + `curate_pack_v2` + holdout |
| `scripts/patch_hf_to_system_one.py` | Idempotent wire into nugatron `hf_to_system_one.py` (UTF-8, no BOM) |
| `scripts/smoke_pack_v2.py` | Count L3 actions / tiers / `champion=false` / holdout ≥20% |
| `scripts/apply_and_run_pack_v2.ps1` | Copy + patch + run + smoke on nugatron. No FT. |
| `scripts/lab/run_ultradata_harvest.py` | Lean harvest (agent 40 / code 40 / math 30) |
| `scripts/lab/finalize_manifest.py` | Rewrite `MANIFEST.json` to the pack-hop schema |
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

No torch, no Hugging Face download, no `--go`, no FT. Tests exercise
classification heuristics, holdout pairing, the pack smoke against a tiny
in-memory fixture, manifest hashing, and the idempotent factory patch.

## Host apply (nugatron only, not CI)

```powershell
$env:PACK_V2_HANDOFF = "C:\Users\jcdav\workspace\dottie-os"
powershell -ExecutionPolicy Bypass -File "$env:PACK_V2_HANDOFF\scripts\apply_and_run_pack_v2.ps1"
```

Champion / LIVE / FT stay untouched.
