# dottie-os curation mirror (UltraData curriculum factory + harvest/hop)

**dottie-os** is the local sidecar that serves System One (`POST /decide`) on
your machine or tailnet. It owns port `:8770`, and the Dottie router reaches
it through `DOTTIE_OS_URL` (see `docs/ROUTER.md`). The sidecar itself lives on
nugatron under `C:\Users\jcdav\workspace\dottie-os`. **This tree is not the
sidecar.** It is the git mirror of the sidecar's curation side: the UltraData
factory, harvest and hop scripts.

**Out of scope for this tree:** serving on `:8770`, the LIVE gate, and any FT
kick. The LIVE gate source exists only on the offline nugatron disk and is a
blocked follow-up.

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
